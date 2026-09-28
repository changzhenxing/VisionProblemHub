from __future__ import annotations
from collections import Counter
from datetime import date, datetime
import json, re, uuid
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from .models import Issue, IssueEvent, IssueRetrospective, ProjectRetrospective, KnowledgeCase, Attachment, Project
from .db import DATA_DIR

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

RETRO_FIELDS = ["phenomenon","impact","process_summary","root_cause","final_solution","validation_result","lessons","prevention"]
PROJECT_RETRO_FIELDS = ["summary","key_problems","delay_analysis","lessons","improvements","knowledge_summary"]
KNOWLEDGE_FIELDS = ["title","scene","problem","root_cause","attempts_summary","final_solution","validation","lessons","prevention","applicability","tags","confidence_state"]


def loads_list(s: str | None):
    try: return list(json.loads(s or "[]"))
    except Exception: return []

def dumps(v): return json.dumps(v, ensure_ascii=False)

def is_delayed(i: Issue) -> bool:
    end = i.actual_close_at.date() if i.actual_close_at else date.today()
    if i.status == "已关闭" and i.actual_close_at:
        return end > i.planned_close_date
    return i.status != "已关闭" and date.today() > i.planned_close_date

def delay_days(i: Issue) -> int:
    end = i.actual_close_at.date() if i.actual_close_at else date.today()
    return max(0, (end - i.planned_close_date).days)

def project_health(p: Project) -> str:
    opens = [i for i in p.issues if i.status != "已关闭"]
    if any(i.status == "阻塞" for i in opens): return "阻塞"
    if any(i.status == "有风险" or is_delayed(i) or i.priority == "紧急重要" for i in opens): return "有风险"
    return "正常"

def media_kind(mime: str, name: str) -> str:
    mime=(mime or "").lower(); name=name.lower()
    if mime.startswith("image/") or name.endswith((".jpg",".jpeg",".png",".webp",".bmp",".gif")): return "image"
    if mime.startswith("video/") or name.endswith((".mp4",".mov",".avi",".mkv",".webm")): return "video"
    return "file"

def save_attachment(db: Session, event: IssueEvent, upload, role: str, actor_id: int | None):
    suffix = Path(upload.filename or "file").suffix[:16]
    issue_dir = UPLOAD_DIR / f"project_{event.issue.project_id}" / f"issue_{event.issue_id}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{suffix}"
    dest = issue_dir / stored
    data = upload.file.read()
    dest.write_bytes(data)
    rel = dest.relative_to(DATA_DIR).as_posix()
    a=Attachment(event_id=event.id, original_name=upload.filename or stored, stored_name=stored,
                 mime_type=upload.content_type or "application/octet-stream", media_kind=media_kind(upload.content_type or "", upload.filename or ""),
                 role=role, size_bytes=len(data), relative_path=rel, uploaded_by_id=actor_id)
    db.add(a)
    return a

def add_event(db: Session, issue: Issue, actor_id: int | None, event_type: str, content: str = "", outcome: str | None = None, metadata: dict | None = None):
    e=IssueEvent(issue_id=issue.id, actor_id=actor_id, event_type=event_type, content=content or "", outcome=outcome,
                 metadata_json=dumps(metadata) if metadata else None)
    db.add(e); db.flush()
    return e

def sentence_candidates(text: str):
    if not text: return []
    return [x.strip() for x in re.split(r"[。！？\n;；]", text) if x.strip()]

def _last_event(events, types, outcome=None):
    xs=[e for e in events if e.event_type in types and (outcome is None or e.outcome==outcome) and e.content.strip()]
    return xs[-1] if xs else None

def _auto_issue_fields(issue: Issue):
    events=list(issue.events)
    work=[e for e in events if e.event_type in {"进展反馈","解决办法","验证结果","根因判断"} and e.content.strip()]
    process=[]
    for e in work:
        suffix=f"（{e.outcome}）" if e.outcome else ""
        process.append(f"{e.created_at:%m/%d %H:%M} {e.event_type}{suffix}：{e.content}")
    root=_last_event(events,{"根因判断"})
    if root: root_text=root.content
    else:
        root_text="待人工确认"
        for e in reversed(work):
            ss=sentence_candidates(e.content)
            hit=next((s for s in ss if any(k in s for k in ["根因","原因","因为","由于","定位到","确认是","确认由"])),None)
            if hit: root_text=hit; break
    sol=_last_event(events,{"解决办法"},"成功") or _last_event(events,{"解决办法"})
    vals=[e for e in events if e.event_type=="验证结果" and e.content.strip()]
    val_text="\n".join(f"- {e.content}" for e in vals[-5:]) or (issue.close_standard or "待补充验证结果")
    failed=[e for e in events if e.event_type=="解决办法" and e.outcome in {"失败","部分有效"} and e.content.strip()]
    lessons=[]
    if failed:
        lessons.append("已尝试但未完全奏效的方案："+"；".join(f"{e.content}（{e.outcome}）" for e in failed[-5:]))
    if sol:
        lessons.append("最终有效方案："+sol.content)
    impact=f"优先级：{issue.priority}；当前状态：{issue.status}"
    if is_delayed(issue): impact += f"；已延期{delay_days(issue)}天"
    prevention="待人工确认。建议结合根因与验证结果，补充同类项目的前置检查或标准化措施。"
    return {
        "phenomenon": issue.description,
        "impact": impact,
        "process_summary": "\n".join(process) or "暂无处理过程记录",
        "root_cause": root_text,
        "final_solution": sol.content if sol else "待形成最终解决办法",
        "validation_result": val_text,
        "lessons": "\n".join(lessons) if lessons else "待从处理过程提炼",
        "prevention": prevention,
    }

def ensure_issue_retro(db: Session, issue: Issue, force=False):
    r=db.scalar(select(IssueRetrospective).where(IssueRetrospective.issue_id==issue.id))
    if not r:
        r=IssueRetrospective(issue_id=issue.id); db.add(r); db.flush()
    auto=_auto_issue_fields(issue); locked=set(loads_list(r.locked_fields_json))
    for k,v in auto.items():
        if force or k not in locked: setattr(r,k,v)
    r.auto_generated_at=datetime.now()
    ensure_knowledge_case(db, issue, r, force=force)
    return r

def ensure_knowledge_case(db: Session, issue: Issue, retro: IssueRetrospective | None=None, force=False):
    if retro is None:
        retro=db.scalar(select(IssueRetrospective).where(IssueRetrospective.issue_id==issue.id))
    k=db.scalar(select(KnowledgeCase).where(KnowledgeCase.issue_id==issue.id))
    if not k:
        k=KnowledgeCase(issue_id=issue.id, title=f"{issue.issue_type}｜{issue.description[:80]}"); db.add(k); db.flush()
    locked=set(loads_list(k.locked_fields_json))
    attempts=[e for e in issue.events if e.event_type=="解决办法" and e.content.strip()]
    evidence=sum(len(e.attachments) for e in issue.events)
    auto={
        "title": f"{issue.issue_type}｜{issue.description[:80]}",
        "scene": f"项目：{issue.project.name}；阶段：{issue.project.current_stage}；问题类型：{issue.issue_type}",
        "problem": issue.description,
        "root_cause": retro.root_cause if retro else "待人工确认",
        "attempts_summary": "\n".join(f"- {e.content}"+(f"（{e.outcome}）" if e.outcome else "") for e in attempts) or "暂无方案尝试记录",
        "final_solution": retro.final_solution if retro else "",
        "validation": retro.validation_result if retro else "",
        "lessons": retro.lessons if retro else "",
        "prevention": retro.prevention if retro else "",
        "applicability": "待人工补充适用/不适用条件",
        "tags": f"{issue.issue_type},{issue.project.current_stage}",
    }
    for field,val in auto.items():
        if force or field not in locked: setattr(k,field,val)
    if retro and retro.confirmed_at and k.confidence_state=="自动提取": k.confidence_state="人工确认"
    k.evidence_count=evidence
    return k

def _project_auto_fields(project: Project):
    issues=list(project.issues); total=len(issues); closed=[i for i in issues if i.status=="已关闭"]
    delayed=[i for i in issues if is_delayed(i)]
    type_counts=Counter(i.issue_type for i in issues)
    reasons=Counter((i.delay_reason or "未填写延期原因").strip() for i in delayed)
    major=sorted(issues,key=lambda i:(0 if i.status=="阻塞" else 1,0 if i.priority=="紧急重要" else 1,-delay_days(i),i.id))[:8]
    retros=[]
    for i in issues:
        r=getattr(i,"_retro_cache",None)
        if r is None: r=None
        if not r: continue
        if r.lessons and r.lessons not in retros: retros.append(r.lessons)
    summary=(f"项目共记录{total}个问题，已关闭{len(closed)}个，当前未关闭{total-len(closed)}个；"
             f"延期{len(delayed)}个，延期率{(len(delayed)/total*100 if total else 0):.1f}%。"
             +(" 问题分布："+"、".join(f"{k}{v}个" for k,v in type_counts.items()) if type_counts else ""))
    key="\n".join(f"- [{i.issue_type}/{i.priority}/{i.status}] {i.description}" for i in major) or "暂无重点问题"
    delay="\n".join(f"- {k or '未填写延期原因'}：{v}次" for k,v in reasons.most_common()) or "无延期问题"
    return {"summary":summary,"key_problems":key,"delay_analysis":delay,
            "lessons":"\n\n".join(retros[:10]) or "待从问题复盘自动汇总",
            "improvements":"待结合问题复盘中的预防措施确认后形成",
            "knowledge_summary":f"已自动形成{total}个问题案例，可在知识库继续确认与复用。"}

def ensure_project_retro(db: Session, project: Project, force=False):
    # ensure issue retros first and cache for aggregation
    for i in project.issues:
        r=ensure_issue_retro(db,i,force=False); setattr(i,"_retro_cache",r)
    r=db.scalar(select(ProjectRetrospective).where(ProjectRetrospective.project_id==project.id))
    if not r:
        r=ProjectRetrospective(project_id=project.id); db.add(r); db.flush()
    auto=_project_auto_fields(project); locked=set(loads_list(r.locked_fields_json))
    for k,v in auto.items():
        if force or k not in locked: setattr(r,k,v)
    r.auto_generated_at=datetime.now()
    return r
