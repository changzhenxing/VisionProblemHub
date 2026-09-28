from __future__ import annotations
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict
import json
from fastapi import FastAPI, Depends, HTTPException, Query, Form, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload, joinedload

from .db import Base, engine, get_db, DATA_DIR
from .models import User, Project, ProjectEvent, Issue, IssueEvent, Attachment, IssueRetrospective, ProjectRetrospective, KnowledgeCase
from .schemas import *
from .services import (
    is_delayed, delay_days, project_health, add_event, save_attachment,
    ensure_issue_retro, ensure_project_retro, ensure_knowledge_case,
    loads_list, dumps, UPLOAD_DIR, RETRO_FIELDS, PROJECT_RETRO_FIELDS, KNOWLEDGE_FIELDS,
)

Base.metadata.create_all(bind=engine)
app=FastAPI(title="以问题驱动的工业视觉项目管理与知识沉淀平台", version="2.0.0")
STATIC_DIR=Path(__file__).resolve().parent/"static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

@app.get("/")
def root(): return FileResponse(STATIC_DIR/"index.html")

@app.get("/api/config")
def config():
    return {"stages":STAGES,"issue_types":ISSUE_TYPES,"priorities":PRIORITIES,"issue_statuses":ISSUE_STATUSES,
            "event_types":EVENT_TYPES,"event_outcomes":EVENT_OUTCOMES,"attachment_roles":ATTACHMENT_ROLES,
            "knowledge_states":KNOWLEDGE_STATES}


def get_issue(db: Session, issue_id: int) -> Issue:
    stmt=(select(Issue).where(Issue.id==issue_id)
          .options(joinedload(Issue.project).joinedload(Project.manager), joinedload(Issue.owner), joinedload(Issue.creator),
                   selectinload(Issue.events).joinedload(IssueEvent.actor), selectinload(Issue.events).selectinload(IssueEvent.attachments)))
    i=db.scalar(stmt)
    if not i: raise HTTPException(404,"问题不存在")
    return i

def get_project(db: Session, project_id: int) -> Project:
    stmt=(select(Project).where(Project.id==project_id)
          .options(joinedload(Project.manager), selectinload(Project.issues).joinedload(Issue.owner),
                   selectinload(Project.issues).selectinload(Issue.events).selectinload(IssueEvent.attachments), selectinload(Project.events).joinedload(ProjectEvent.actor)))
    p=db.scalar(stmt)
    if not p: raise HTTPException(404,"项目不存在")
    return p

def attachment_dict(a: Attachment):
    return {"id":a.id,"name":a.original_name,"mime_type":a.mime_type,"media_kind":a.media_kind,"role":a.role,
            "size_bytes":a.size_bytes,"url":"/uploads/"+a.relative_path.removeprefix("uploads/"),
            "uploaded_at":a.uploaded_at.isoformat(timespec="minutes")}

def event_dict(e: IssueEvent):
    try: meta=json.loads(e.metadata_json) if e.metadata_json else None
    except Exception: meta=None
    return {"id":e.id,"event_type":e.event_type,"content":e.content,"outcome":e.outcome,"metadata":meta,
            "actor_id":e.actor_id,"actor_name":e.actor.name if e.actor else "系统",
            "created_at":e.created_at.isoformat(timespec="minutes"),"attachments":[attachment_dict(a) for a in e.attachments]}

def project_event_dict(e: ProjectEvent):
    try: meta=json.loads(e.metadata_json) if e.metadata_json else None
    except Exception: meta=None
    return {"id":e.id,"event_type":e.event_type,"content":e.content,"metadata":meta,
            "actor_id":e.actor_id,"actor_name":e.actor.name if e.actor else "系统",
            "created_at":e.created_at.isoformat(timespec="minutes")}

def issue_brief(i: Issue):
    return {"id":i.id,"project_id":i.project_id,"project_name":i.project.name if i.project else None,"issue_type":i.issue_type,
            "description":i.description,"priority":i.priority,"status":i.status,"owner_id":i.owner_id,
            "owner_name":i.owner.name if i.owner else None,"planned_close_date":i.planned_close_date.isoformat(),
            "actual_close_at":i.actual_close_at.isoformat(timespec="minutes") if i.actual_close_at else None,
            "close_standard":i.close_standard,"delay_reason":i.delay_reason,"is_delayed":is_delayed(i),"delay_days":delay_days(i),
            "created_at":i.created_at.isoformat(timespec="minutes"),"updated_at":i.updated_at.isoformat(timespec="minutes")}

def project_dict(p: Project):
    opens=[i for i in p.issues if i.status!="已关闭"]
    return {"id":p.id,"name":p.name,"manager_id":p.manager_id,"manager_name":p.manager.name if p.manager else None,
            "current_stage":p.current_stage,"overall_status":project_health(p),"planned_completion_date":p.planned_completion_date.isoformat(),
            "actual_completion_date":p.actual_completion_date.isoformat() if p.actual_completion_date else None,"description":p.description,
            "counts":{"open":len(opens),"critical":sum(i.priority=="紧急重要" for i in opens),
                      "blocked":sum(i.status=="阻塞" for i in opens),"delayed":sum(is_delayed(i) for i in opens),"all":len(p.issues)}}

def retro_dict(r: IssueRetrospective):
    return {k:getattr(r,k) for k in RETRO_FIELDS} | {"issue_id":r.issue_id,"locked_fields":loads_list(r.locked_fields_json),
            "confirmed":bool(r.confirmed_at),"confirmed_at":r.confirmed_at.isoformat(timespec="minutes") if r.confirmed_at else None,
            "auto_generated_at":r.auto_generated_at.isoformat(timespec="minutes") if r.auto_generated_at else None}

def project_retro_dict(r: ProjectRetrospective):
    return {k:getattr(r,k) for k in PROJECT_RETRO_FIELDS} | {"project_id":r.project_id,"locked_fields":loads_list(r.locked_fields_json),
            "confirmed":bool(r.confirmed_at),"confirmed_at":r.confirmed_at.isoformat(timespec="minutes") if r.confirmed_at else None,
            "auto_generated_at":r.auto_generated_at.isoformat(timespec="minutes") if r.auto_generated_at else None}

def knowledge_dict(k: KnowledgeCase, issue: Issue | None=None):
    d={f:getattr(k,f) for f in KNOWLEDGE_FIELDS}
    d.update({"id":k.id,"issue_id":k.issue_id,"evidence_count":k.evidence_count,"locked_fields":loads_list(k.locked_fields_json),
              "updated_at":k.updated_at.isoformat(timespec="minutes")})
    if issue:
        d.update({"project_id":issue.project_id,"project_name":issue.project.name,"issue_type":issue.issue_type,"status":issue.status})
    return d

# ---- Users ----
@app.get("/api/users")
def list_users(db:Session=Depends(get_db)):
    return [{"id":u.id,"name":u.name,"role":u.role} for u in db.scalars(select(User).order_by(User.id)).all()]

@app.post("/api/users")
def create_user(payload:dict, db:Session=Depends(get_db)):
    name=str(payload.get("name","")).strip(); role=str(payload.get("role","团队成员")).strip() or "团队成员"
    if not name: raise HTTPException(400,"姓名不能为空")
    if db.scalar(select(User).where(User.name==name)): raise HTTPException(409,"用户已存在")
    u=User(name=name,role=role); db.add(u); db.commit(); db.refresh(u)
    return {"id":u.id,"name":u.name,"role":u.role}

# ---- Projects ----
@app.get("/api/projects")
def list_projects(db:Session=Depends(get_db)):
    ps=db.scalars(select(Project).options(joinedload(Project.manager),selectinload(Project.issues)).order_by(Project.planned_completion_date)).all()
    return [project_dict(p) for p in ps]

@app.post("/api/projects")
def create_project(payload:ProjectCreate, db:Session=Depends(get_db)):
    if payload.current_stage not in STAGES: raise HTTPException(400,"项目阶段非法")
    if not db.get(User,payload.manager_id): raise HTTPException(400,"项目负责人不存在")
    p=Project(**payload.model_dump()); db.add(p); db.flush()
    db.add(ProjectEvent(project_id=p.id,actor_id=payload.manager_id,event_type="创建项目",content=f"创建项目：{p.name}"))
    db.commit(); db.refresh(p)
    return project_dict(get_project(db,p.id))

@app.patch("/api/projects/{project_id}")
def patch_project(project_id:int,payload:ProjectPatch,db:Session=Depends(get_db)):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,"项目不存在")
    data=payload.model_dump(exclude_unset=True)
    if data.get("current_stage") and data["current_stage"] not in STAGES: raise HTTPException(400,"项目阶段非法")
    actor_id=data.pop("actor_id",None) or p.manager_id
    changes=[]
    for k,v in data.items():
        old=getattr(p,k)
        if old==v: continue
        setattr(p,k,v); changes.append((k,old,v))
    labels={"name":"项目名称","manager_id":"项目负责人","current_stage":"项目阶段","planned_completion_date":"总体计划完成时间","description":"项目说明"}
    for k,old,newv in changes:
        def pv(x):
            if k=="manager_id" and x: return db.get(User,int(x)).name if db.get(User,int(x)) else str(x)
            return x.isoformat() if isinstance(x,(date,datetime)) else ("" if x is None else str(x))
        db.add(ProjectEvent(project_id=p.id,actor_id=actor_id,event_type=("阶段变化" if k=="current_stage" else "项目修改"),
                            content=f"{labels[k]}：{pv(old)} → {pv(newv)}",metadata_json=dumps({"field":k,"before":pv(old),"after":pv(newv)})))
    if p.current_stage=="验收关闭" and not p.actual_completion_date: p.actual_completion_date=date.today()
    elif p.current_stage!="验收关闭": p.actual_completion_date=None
    db.commit(); db.expire_all()
    p=get_project(db,project_id); ensure_project_retro(db,p); db.commit()
    return project_dict(p)|{"meaningful_changes":len(changes)}

@app.get("/api/projects/{project_id}")
def project_detail(project_id:int,db:Session=Depends(get_db)):
    p=get_project(db,project_id)
    return project_dict(p)|{"issues":[issue_brief(i) for i in p.issues],"events":[project_event_dict(e) for e in p.events]}

# ---- Issues ----
@app.get("/api/issues")
def list_issues(project_id:int|None=None,owner_id:int|None=None,status:str|None=None,priority:str|None=None,issue_type:str|None=None,
                delayed_only:bool=False,q:str|None=None,db:Session=Depends(get_db)):
    stmt=select(Issue).options(joinedload(Issue.project),joinedload(Issue.owner)).order_by(Issue.planned_close_date,Issue.id)
    if project_id: stmt=stmt.where(Issue.project_id==project_id)
    if owner_id: stmt=stmt.where(Issue.owner_id==owner_id)
    if status: stmt=stmt.where(Issue.status==status)
    if priority: stmt=stmt.where(Issue.priority==priority)
    if issue_type: stmt=stmt.where(Issue.issue_type==issue_type)
    if q: stmt=stmt.where(Issue.description.contains(q))
    xs=db.scalars(stmt).all()
    if delayed_only: xs=[i for i in xs if is_delayed(i)]
    return [issue_brief(i) for i in xs]

@app.post("/api/issues")
def create_issue(payload:IssueCreate,db:Session=Depends(get_db)):
    if payload.issue_type not in ISSUE_TYPES or payload.priority not in PRIORITIES or payload.status not in ISSUE_STATUSES: raise HTTPException(400,"问题字段非法")
    if not db.get(Project,payload.project_id): raise HTTPException(400,"项目不存在")
    if not db.get(User,payload.owner_id): raise HTTPException(400,"Owner不存在")
    i=Issue(**payload.model_dump()); db.add(i); db.flush()
    add_event(db,i,payload.created_by_id,"创建问题",payload.description,metadata={"issue_type":payload.issue_type,"priority":payload.priority,"owner_id":payload.owner_id})
    db.commit(); i=get_issue(db,i.id); ensure_issue_retro(db,i); db.commit()
    return issue_brief(i)

@app.get("/api/issues/{issue_id}")
def issue_detail(issue_id:int,db:Session=Depends(get_db)):
    i=get_issue(db,issue_id); r=ensure_issue_retro(db,i); db.commit(); k=ensure_knowledge_case(db,i,r); db.commit()
    return issue_brief(i)|{"events":[event_dict(e) for e in i.events],"retrospective":retro_dict(r),"knowledge":knowledge_dict(k,i)}

CHANGE_FIELDS={
    "issue_type":("问题类型修改","问题类型"),"description":("问题描述修改","问题描述"),"priority":("优先级变化","优先级"),
    "status":("状态变化","状态"),"owner_id":("Owner变化","问题Owner"),"planned_close_date":("计划时间变化","计划关闭时间"),
    "close_standard":("关闭标准修改","关闭标准"),"delay_reason":("延期原因修改","延期原因")}

def display_value(db,field,value):
    if field=="owner_id" and value: return db.get(User,int(value)).name if db.get(User,int(value)) else str(value)
    if isinstance(value,(date,datetime)): return value.isoformat()
    return "" if value is None else str(value)

@app.patch("/api/issues/{issue_id}")
def patch_issue(issue_id:int,payload:IssuePatch,db:Session=Depends(get_db)):
    i=get_issue(db,issue_id); data=payload.model_dump(exclude_unset=True); actor=data.pop("actor_id")
    if data.get("issue_type") and data["issue_type"] not in ISSUE_TYPES: raise HTTPException(400,"问题类型非法")
    if data.get("priority") and data["priority"] not in PRIORITIES: raise HTTPException(400,"优先级非法")
    if data.get("status") and data["status"] not in ISSUE_STATUSES: raise HTTPException(400,"问题状态非法")
    changes=[]
    old_status=i.status
    for field,new in data.items():
        old=getattr(i,field)
        if old==new: continue
        setattr(i,field,new); changes.append((field,old,new))
    if old_status!="已关闭" and i.status=="已关闭": i.actual_close_at=datetime.now()
    if old_status=="已关闭" and i.status!="已关闭": i.actual_close_at=None
    for field,old,new in changes:
        et,label=CHANGE_FIELDS[field]
        if field=="status" and old=="已关闭" and new!="已关闭": et="重新打开"
        if field=="status" and new=="已关闭": et="问题关闭"
        add_event(db,i,actor,et,f"{label}：{display_value(db,field,old)} → {display_value(db,field,new)}",metadata={"field":field,"before":display_value(db,field,old),"after":display_value(db,field,new)})
    db.commit(); db.expire_all(); i=get_issue(db,issue_id); ensure_issue_retro(db,i); p=get_project(db,i.project_id); ensure_project_retro(db,p); db.commit()
    return issue_brief(i)|{"meaningful_changes":len(changes)}

@app.post("/api/issues/{issue_id}/creation-attachments")
def add_creation_attachments(issue_id:int,actor_id:int=Form(...),attachment_role:str=Form("问题证据"),files:list[UploadFile]=File(...),db:Session=Depends(get_db)):
    i=get_issue(db,issue_id)
    e=next((e for e in i.events if e.event_type=="创建问题"),None)
    if not e: e=add_event(db,i,actor_id,"进展反馈","补充问题创建资料")
    for f in files: save_attachment(db,e,f,attachment_role,actor_id)
    event_id=e.id
    db.commit(); db.expire_all(); i=get_issue(db,issue_id); ensure_issue_retro(db,i); db.commit(); db.expire_all(); i=get_issue(db,issue_id)
    return {"attachments":[attachment_dict(a) for a in next(x for x in i.events if x.id==event_id).attachments]}

@app.post("/api/issues/{issue_id}/events")
def create_issue_event(issue_id:int,actor_id:int=Form(...),event_type:str=Form(...),content:str=Form(""),outcome:str|None=Form(None),
                       attachment_role:str=Form("其他"),files:list[UploadFile]|None=File(None),db:Session=Depends(get_db)):
    if event_type not in EVENT_TYPES: raise HTTPException(400,"事件类型非法")
    if outcome and outcome not in EVENT_OUTCOMES: raise HTTPException(400,"事件结果非法")
    if attachment_role not in ATTACHMENT_ROLES: raise HTTPException(400,"附件角色非法")
    i=get_issue(db,issue_id); e=add_event(db,i,actor_id,event_type,content,outcome)
    if i.status=="待处理" and event_type in {"进展反馈","解决办法","根因判断"}:
        old=i.status; i.status="处理中"
        add_event(db,i,actor_id,"状态变化",f"状态：{old} → 处理中",metadata={"field":"status","before":old,"after":"处理中","automatic":True})
    for f in files or []: save_attachment(db,e,f,attachment_role,actor_id)
    event_id=e.id
    db.commit(); db.expire_all(); i=get_issue(db,issue_id); r=ensure_issue_retro(db,i); p=get_project(db,i.project_id); ensure_project_retro(db,p); db.commit(); db.expire_all()
    i=get_issue(db,issue_id); e=next(x for x in i.events if x.id==event_id)
    return {"event":event_dict(e),"retrospective":retro_dict(r)}

# ---- Retrospectives ----
@app.get("/api/issues/{issue_id}/retrospective")
def issue_retrospective(issue_id:int,db:Session=Depends(get_db)):
    i=get_issue(db,issue_id); r=ensure_issue_retro(db,i); db.commit(); return retro_dict(r)

@app.post("/api/issues/{issue_id}/retrospective/regenerate")
def regenerate_issue_retro(issue_id:int,force:bool=False,db:Session=Depends(get_db)):
    i=get_issue(db,issue_id); r=ensure_issue_retro(db,i,force=force); db.commit(); return retro_dict(r)

@app.patch("/api/issues/{issue_id}/retrospective")
def patch_issue_retro(issue_id:int,payload:ManualRetrospectivePatch,db:Session=Depends(get_db)):
    i=get_issue(db,issue_id); r=ensure_issue_retro(db,i)
    locked=set(loads_list(r.locked_fields_json)); changed={}
    for field,val in payload.values.items():
        if field not in RETRO_FIELDS: continue
        old=getattr(r,field); setattr(r,field,val); locked.add(field); changed[field]={"before":old,"after":val}
    r.locked_fields_json=dumps(sorted(locked))
    if payload.confirm: r.confirmed_by_id=payload.actor_id; r.confirmed_at=datetime.now()
    add_event(db,i,payload.actor_id,"复盘人工修订",f"人工修订复盘字段：{', '.join(changed.keys())}",metadata={"changes":changed,"confirm":payload.confirm})
    k=ensure_knowledge_case(db,i,r)
    if payload.confirm and k.confidence_state=="自动提取": k.confidence_state="人工确认"
    db.commit(); return retro_dict(r)

@app.get("/api/projects/{project_id}/retrospective")
def get_project_retro(project_id:int,db:Session=Depends(get_db)):
    p=get_project(db,project_id); r=ensure_project_retro(db,p); db.commit()
    return {"project":project_dict(p),"retrospective":project_retro_dict(r)}

@app.post("/api/projects/{project_id}/retrospective/regenerate")
def regenerate_project_retro(project_id:int,force:bool=False,db:Session=Depends(get_db)):
    p=get_project(db,project_id); r=ensure_project_retro(db,p,force=force); db.commit(); return project_retro_dict(r)

@app.patch("/api/projects/{project_id}/retrospective")
def patch_project_retro(project_id:int,payload:ManualRetrospectivePatch,db:Session=Depends(get_db)):
    p=get_project(db,project_id); r=ensure_project_retro(db,p); locked=set(loads_list(r.locked_fields_json))
    for field,val in payload.values.items():
        if field in PROJECT_RETRO_FIELDS: setattr(r,field,val); locked.add(field)
    r.locked_fields_json=dumps(sorted(locked))
    if payload.confirm: r.confirmed_by_id=payload.actor_id; r.confirmed_at=datetime.now()
    db.add(ProjectEvent(project_id=project_id,actor_id=payload.actor_id,event_type="项目复盘人工修订",content=f"人工修订项目复盘字段：{', '.join(payload.values.keys())}"))
    db.commit(); return project_retro_dict(r)

# ---- Knowledge ----
@app.get("/api/knowledge")
def list_knowledge(q:str|None=None,issue_type:str|None=None,confidence_state:str|None=None,project_id:int|None=None,db:Session=Depends(get_db)):
    stmt=(select(KnowledgeCase,Issue).join(Issue,KnowledgeCase.issue_id==Issue.id).options(joinedload(Issue.project)).order_by(KnowledgeCase.updated_at.desc()))
    if issue_type: stmt=stmt.where(Issue.issue_type==issue_type)
    if confidence_state: stmt=stmt.where(KnowledgeCase.confidence_state==confidence_state)
    if project_id: stmt=stmt.where(Issue.project_id==project_id)
    rows=db.execute(stmt).all(); out=[]
    for k,i in rows:
        d=knowledge_dict(k,i)
        if q:
            hay=" ".join(str(d.get(x) or "") for x in ["title","problem","root_cause","final_solution","lessons","tags"])
            if q.lower() not in hay.lower(): continue
        out.append(d)
    return out

@app.get("/api/knowledge/{case_id}")
def get_knowledge(case_id:int,db:Session=Depends(get_db)):
    k=db.get(KnowledgeCase,case_id)
    if not k: raise HTTPException(404,"知识案例不存在")
    i=get_issue(db,k.issue_id); return knowledge_dict(k,i)|{"events":[event_dict(e) for e in i.events]}

@app.patch("/api/knowledge/{case_id}")
def patch_knowledge(case_id:int,payload:KnowledgePatch,db:Session=Depends(get_db)):
    k=db.get(KnowledgeCase,case_id)
    if not k: raise HTTPException(404,"知识案例不存在")
    locked=set(loads_list(k.locked_fields_json)); changed=[]
    for field,val in payload.values.items():
        if field not in KNOWLEDGE_FIELDS: continue
        if field=="confidence_state" and val not in KNOWLEDGE_STATES: raise HTTPException(400,"可信度状态非法")
        setattr(k,field,val); locked.add(field); changed.append(field)
    k.locked_fields_json=dumps(sorted(locked)); i=get_issue(db,k.issue_id)
    add_event(db,i,payload.actor_id,"知识人工修订",f"人工修订知识字段：{', '.join(changed)}")
    db.commit(); return knowledge_dict(k,i)

@app.post("/api/knowledge/{case_id}/regenerate")
def regenerate_knowledge(case_id:int,force:bool=False,db:Session=Depends(get_db)):
    k=db.get(KnowledgeCase,case_id)
    if not k: raise HTTPException(404,"知识案例不存在")
    i=get_issue(db,k.issue_id); r=ensure_issue_retro(db,i,force=False); k=ensure_knowledge_case(db,i,r,force=force); db.commit(); return knowledge_dict(k,i)

# ---- Workbench / Stats ----
@app.get("/api/workbench")
def workbench(owner_id:int,db:Session=Depends(get_db)):
    xs=db.scalars(select(Issue).where(Issue.owner_id==owner_id,Issue.status!="已关闭").options(joinedload(Issue.project),joinedload(Issue.owner))).all()
    today=date.today(); week=today+timedelta(days=7)
    def sortkey(i): return (0 if i.priority=="紧急重要" else 1,0 if i.status=="阻塞" else 1,i.planned_close_date)
    xs=sorted(xs,key=sortkey)
    return {"counts":{"all":len(xs),"critical":sum(i.priority=="紧急重要" for i in xs),"due_week":sum(today<=i.planned_close_date<=week for i in xs),"delayed":sum(is_delayed(i) for i in xs),"blocked":sum(i.status=="阻塞" for i in xs)},
            "issues":[issue_brief(i) for i in xs]}

@app.get("/api/stats")
def stats(days:int=30,project_id:int|None=None,db:Session=Depends(get_db)):
    start=datetime.now()-timedelta(days=max(1,min(days,365)))
    stmt=select(Issue).options(joinedload(Issue.project),joinedload(Issue.owner))
    if project_id: stmt=stmt.where(Issue.project_id==project_id)
    xs=db.scalars(stmt).all(); recent=[i for i in xs if i.created_at>=start]
    created=Counter(i.created_at.date().isoformat() for i in recent)
    closed=Counter(i.actual_close_at.date().isoformat() for i in xs if i.actual_close_at and i.actual_close_at>=start)
    cur=start.date(); trend=[]
    while cur<=date.today():
        s=cur.isoformat(); trend.append({"date":s,"created":created[s],"closed":closed[s]}); cur+=timedelta(days=1)
    openxs=[i for i in xs if i.status!="已关闭"]
    types=Counter(i.issue_type for i in xs)
    delay_reasons=Counter((i.delay_reason or "未填写延期原因").strip() for i in xs if is_delayed(i))
    return {"summary":{"total":len(xs),"open":len(openxs),"critical":sum(i.priority=="紧急重要" for i in openxs),"blocked":sum(i.status=="阻塞" for i in openxs),
                       "delayed":sum(is_delayed(i) for i in openxs),"delay_rate":round(sum(is_delayed(i) for i in xs)/len(xs)*100,1) if xs else 0},
            "trend":trend,"types":[{"name":k,"count":v} for k,v in types.items()],"delay_reasons":[{"name":k or "未填写延期原因","count":v} for k,v in delay_reasons.most_common(10)]}

@app.get("/api/knowledge/export/agent")
def agent_export(db:Session=Depends(get_db)):
    """Multimodal structured export for future RAG/Agent ingestion."""
    rows=db.execute(select(KnowledgeCase,Issue).join(Issue,KnowledgeCase.issue_id==Issue.id).options(joinedload(Issue.project))).all()
    out=[]
    for k,i0 in rows:
        if k.confidence_state=="已废弃": continue
        i=get_issue(db,i0.id); r=ensure_issue_retro(db,i)
        out.append({"case":knowledge_dict(k,i),"issue":issue_brief(i),"retrospective":retro_dict(r),
                    "events":[event_dict(e) for e in i.events]})
    db.commit()
    return out
