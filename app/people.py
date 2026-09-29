"""Grounded people views, management conversations and personal reports."""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import can_issue, can_person
from .auth import authenticated_user
from .db import get_db
from .management import audit
from .models import (AuditLog, GrowthAction, Issue, IssueEvent, Notification, OneOnOne,
                     Project, ProjectMember, SkillEvidence, User, WeeklyReport)

router = APIRouter(prefix="/api")
CLOSED = {"已关闭", "已解决"}


def actor(request: Request, db: Session) -> User:
    return authenticated_user(request, db)


def visible_person(db: Session, user: User, person_id: int, *, sensitive: bool = False,
                   manage: bool = False) -> User:
    person = db.get(User, person_id)
    if not person or not can_person(db, user, person, sensitive=sensitive, manage=manage):
        raise HTTPException(404 if not manage else 403, "人员不可访问")
    return person


def visible_issues(db: Session, user: User, items: list[Issue]) -> list[Issue]:
    return [item for item in items if can_issue(db, user, item)]


def person_summary(db: Session, user: User, person: User) -> dict:
    owned = visible_issues(db, user, db.scalars(select(Issue).where(Issue.owner_id == person.id)).all())
    involved_ids = set(db.scalars(select(IssueEvent.issue_id).where(IssueEvent.actor_id == person.id)).all())
    assisted = visible_issues(db, user, [item for item in db.scalars(select(Issue).where(Issue.id.in_(involved_ids))).all()
                                        if item.owner_id != person.id]) if involved_ids else []
    active = [issue for issue in owned if issue.status not in CLOSED]
    project_ids = sorted({issue.project_id for issue in active})
    return {"id": person.id, "name": person.name, "team_id": person.team_id,
            "workload": {"open": len(active), "urgent": sum(item.priority in {"紧急重要", "紧急不重要"} for item in active),
                         "blocked": sum(item.status == "阻塞" for item in active),
                         "projects": len(project_ids)},
            "contribution": {"closed_owned": sum(item.status in CLOSED for item in owned),
                             "assisted_issues": len(assisted)},
            "issue_ids": [item.id for item in active], "assisted_issue_ids": [item.id for item in assisted]}


@router.get("/people")
def people(request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    return [person_summary(db, user, person) for person in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))
            if can_person(db, user, person)]


@router.get("/people/{person_id}")
def person_detail(person_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); person = visible_person(db, user, person_id)
    result = person_summary(db, user, person)
    result["recommendations"] = recommendations(db, user, person)
    return result


def recommendations(db: Session, user: User, person: User) -> list[dict]:
    issues = visible_issues(db, user, db.scalars(select(Issue).where(Issue.owner_id == person.id)).all())
    today = date.today(); result = []
    active = [issue for issue in issues if issue.status not in CLOSED]
    for issue in active:
        if issue.status == "阻塞":
            result.append({"rule": "blocked", "text": "问题阻塞，建议确认需要协调的资源", "issue_ids": [issue.id]})
        elif issue.planned_close_date < today:
            result.append({"rule": "overdue", "text": "问题超过计划关闭时间，建议确认新计划", "issue_ids": [issue.id]})
        elif issue.updated_at and (datetime.now() - issue.updated_at).days >= 3:
            result.append({"rule": "stale", "text": "问题连续三天无更新，建议了解卡点", "issue_ids": [issue.id]})
    urgent = [issue.id for issue in active if issue.priority in {"紧急重要", "紧急不重要"}]
    if len(urgent) >= 2:
        result.append({"rule": "parallel_urgent", "text": "并行承担多个紧急问题，建议确认工作负荷", "issue_ids": urgent})
    reopened = [issue.id for issue in issues if db.scalar(select(IssueEvent.id).where(
        IssueEvent.issue_id == issue.id, IssueEvent.event_type == "重新打开").limit(1))]
    if reopened:
        result.append({"rule": "reopened", "text": "问题曾重新打开，建议讨论验证或根因", "issue_ids": reopened})
    return result


@router.get("/management/overview")
def management_overview(request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    if "people.read" not in request.state.permissions and "people.manage" not in request.state.permissions:
        raise HTTPException(403, "无权查看管理视图")
    result = []
    for person in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)):
        if can_person(db, user, person) and person.id != user.id:
            cues = recommendations(db, user, person)
            if cues: result.append({"person": person_summary(db, user, person), "recommendations": cues})
    return result


def sync_skill_evidence(db: Session, person: User):
    """Suggest evidence only from closed issues with a recorded outcome; never infer a score."""
    issues = db.scalars(select(Issue).where(Issue.owner_id == person.id, Issue.status.in_(CLOSED))).all()
    for issue in issues:
        if db.scalar(select(SkillEvidence.id).where(SkillEvidence.user_id == person.id,
                                                      SkillEvidence.issue_id == issue.id).limit(1)):
            continue
        event = db.scalar(select(IssueEvent).where(IssueEvent.issue_id == issue.id,
                                                    IssueEvent.actor_id == person.id,
                                                    IssueEvent.outcome.is_not(None)).order_by(IssueEvent.id.desc()))
        if not event:
            continue
        db.add(SkillEvidence(user_id=person.id, issue_id=issue.id, event_id=event.id,
                             skill=issue.issue_type, evidence=f"参与处理并验证：{event.content[:240]}", state="待确认"))
    db.flush()


@router.get("/people/{person_id}/skills")
def person_skills(person_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); person = visible_person(db, user, person_id)
    sync_skill_evidence(db, person); db.commit()
    return [{"id": item.id, "skill": item.skill, "evidence": item.evidence, "state": item.state,
             "issue_id": item.issue_id, "event_id": item.event_id}
            for item in db.scalars(select(SkillEvidence).where(SkillEvidence.user_id == person_id).order_by(SkillEvidence.id.desc()))
            if can_issue(db, user, db.get(Issue, item.issue_id))]


@router.patch("/skills/{evidence_id}")
def confirm_skill(evidence_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    item = db.get(SkillEvidence, evidence_id)
    if not item: raise HTTPException(404, "能力证据不存在")
    visible_person(db, user, item.user_id, manage=True)
    if payload.get("state") not in {"已确认", "已驳回"}: raise HTTPException(400, "状态非法")
    before = {"state": item.state}; item.state = payload["state"]
    audit(db, user.id, "确认能力证据", "skill_evidence", item.id, before, {"state": item.state})
    db.commit(); return {"id": item.id, "state": item.state}


def one_on_one_dict(item: OneOnOne) -> dict:
    return {"id": item.id, "subject_id": item.subject_id, "manager_id": item.manager_id,
            "summary": item.summary, "actions": item.actions, "resource_request": item.resource_request,
            "growth_goal": item.growth_goal, "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
            "created_at": item.created_at.isoformat(timespec="minutes")}


@router.get("/people/{person_id}/one-on-ones")
def one_on_ones(person_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); visible_person(db, user, person_id, sensitive=True)
    items = db.scalars(select(OneOnOne).where(OneOnOne.subject_id == person_id).order_by(OneOnOne.id.desc())).all()
    audit(db, user.id, "查看 1 对 1 纪要", "user", person_id); db.commit()
    return [one_on_one_dict(item) for item in items]


@router.post("/people/{person_id}/one-on-ones")
def add_one_on_one(person_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); visible_person(db, user, person_id, manage=True)
    fields = {key: str(payload.get(key, "")).strip() for key in ("summary", "actions", "resource_request", "growth_goal")}
    if not any(fields.values()) or any(len(value) > 5000 for value in fields.values()):
        raise HTTPException(400, "至少填写一项，每项不超过 5000 字")
    item = OneOnOne(subject_id=person_id, manager_id=user.id, **fields); db.add(item); db.flush()
    audit(db, user.id, "记录 1 对 1", "one_on_one", item.id, after={"subject_id": person_id})
    db.add(Notification(user_id=person_id, kind="待确认沟通纪要", content=f"{user.name}记录了一次 1 对 1，请确认要点"))
    db.commit(); return one_on_one_dict(item)


@router.post("/one-on-ones/{note_id}/confirm")
def confirm_one_on_one(note_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); item = db.get(OneOnOne, note_id)
    if not item or item.subject_id != user.id: raise HTTPException(403, "仅本人可确认")
    if not item.confirmed_at:
        item.confirmed_at = datetime.now()
        if item.growth_goal:
            db.add(GrowthAction(subject_id=user.id, one_on_one_id=item.id, title=item.growth_goal[:200]))
        audit(db, user.id, "确认 1 对 1", "one_on_one", note_id)
        db.commit()
    return one_on_one_dict(item)


@router.get("/people/{person_id}/growth-actions")
def growth_actions(person_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); visible_person(db, user, person_id, sensitive=True)
    return [{"id": item.id, "title": item.title, "due_date": item.due_date.isoformat() if item.due_date else None,
             "status": item.status, "one_on_one_id": item.one_on_one_id}
            for item in db.scalars(select(GrowthAction).where(GrowthAction.subject_id == person_id).order_by(GrowthAction.id.desc()))]


@router.patch("/growth-actions/{action_id}")
def update_growth_action(action_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); item = db.get(GrowthAction, action_id)
    if not item: raise HTTPException(404, "成长行动不存在")
    if user.id != item.subject_id: visible_person(db, user, item.subject_id, manage=True)
    if payload.get("status") not in {"进行中", "已完成", "已取消"}: raise HTTPException(400, "状态非法")
    before = {"status": item.status}; item.status = payload["status"]
    audit(db, user.id, "修改成长行动", "growth_action", item.id, before, {"status": item.status})
    db.commit(); return {"id": item.id, "status": item.status}


@router.get("/notifications")
def notifications(request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    return [{"id": item.id, "kind": item.kind, "content": item.content, "issue_id": item.issue_id,
             "read_at": item.read_at.isoformat() if item.read_at else None,
             "created_at": item.created_at.isoformat(timespec="minutes")}
            for item in db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(100))]


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); item = db.get(Notification, notification_id)
    if not item or item.user_id != user.id: raise HTTPException(404, "提醒不存在")
    item.read_at = item.read_at or datetime.now(); db.commit(); return {"ok": True}


def monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


def report_draft(db: Session, user: User, week: date) -> str:
    end = week + timedelta(days=7)
    events = db.execute(select(IssueEvent, Issue).join(Issue, Issue.id == IssueEvent.issue_id)
                        .where(IssueEvent.actor_id == user.id, IssueEvent.created_at >= datetime.combine(week, datetime.min.time()),
                               IssueEvent.created_at < datetime.combine(end, datetime.min.time()))
                        .order_by(IssueEvent.created_at)).all()
    lines = [f"{week.isoformat()} 周工作草稿", "本周处理："]
    lines.extend(f"- 问题 #{issue.id} {issue.issue_type}：{event.content[:160]}" for event, issue in events)
    if not events: lines.append("- 暂无进展记录")
    due = db.scalars(select(Issue).where(Issue.owner_id == user.id, Issue.planned_close_date >= week,
                                         Issue.planned_close_date < end, ~Issue.status.in_(CLOSED))).all()
    lines.append("待关注：")
    lines.extend(f"- 问题 #{issue.id} {issue.status}，计划 {issue.planned_close_date}" for issue in due)
    if not due: lines.append("- 暂无本周到期问题")
    lines.append("请核对并补充后确认。")
    return "\n".join(lines)


@router.get("/reports/weekly")
def weekly_report(request: Request, week_start: str | None = None, db: Session = Depends(get_db)):
    user = actor(request, db)
    try: week = monday(date.fromisoformat(week_start)) if week_start else monday(date.today())
    except ValueError: raise HTTPException(400, "周日期非法")
    saved = db.scalar(select(WeeklyReport).where(WeeklyReport.user_id == user.id, WeeklyReport.week_start == week))
    return {"week_start": week.isoformat(), "content": saved.content if saved else report_draft(db, user, week),
            "confirmed_at": saved.confirmed_at.isoformat() if saved and saved.confirmed_at else None,
            "source": "人工确认" if saved else "工作记录自动草稿"}


@router.put("/reports/weekly")
def save_weekly_report(payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    if "reports.write" not in request.state.permissions: raise HTTPException(403, "无权确认周报")
    try: week = monday(date.fromisoformat(payload["week_start"]))
    except (KeyError, ValueError, TypeError): raise HTTPException(400, "周日期非法")
    content = str(payload.get("content", "")).strip()
    if not content or len(content) > 20000: raise HTTPException(400, "周报内容须为 1 到 20000 字")
    item = db.scalar(select(WeeklyReport).where(WeeklyReport.user_id == user.id, WeeklyReport.week_start == week))
    if not item: item = WeeklyReport(user_id=user.id, week_start=week, content=content); db.add(item)
    item.content = content; item.confirmed_at = datetime.now() if payload.get("confirm") is True else None
    db.flush(); audit(db, user.id, "保存周报", "weekly_report", item.id, after={"confirmed": bool(item.confirmed_at)})
    db.commit(); return {"week_start": week.isoformat(), "content": content,
                         "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None}


@router.get("/issues/{issue_id}/similar")
def similar_issues(issue_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); issue = db.get(Issue, issue_id)
    if not issue or not can_issue(db, user, issue): raise HTTPException(404, "问题不可访问")
    words = set(re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9]{3,}", issue.description.lower()))
    candidates = db.scalars(select(Issue).where(Issue.id != issue_id, Issue.issue_type == issue.issue_type).limit(200)).all()
    ranked = []
    for candidate in candidates:
        if not can_issue(db, user, candidate): continue
        overlap = words & set(re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9]{3,}", candidate.description.lower()))
        ranked.append({"id": candidate.id, "description": candidate.description[:200], "status": candidate.status,
                       "issue_type": candidate.issue_type, "rule": "同类型 + 关键词重合" if overlap else "同类型",
                       "matching_terms": sorted(overlap)[:5], "score": len(overlap)})
    ranked.sort(key=lambda item: (item["score"], item["id"]), reverse=True)
    return ranked[:5]


@router.get("/audit")
def audit_log(request: Request, db: Session = Depends(get_db)):
    actor(request, db)
    if "audit.read" not in request.state.permissions: raise HTTPException(403, "无权查看审计")
    return [{"id": item.id, "actor_id": item.actor_id, "action": item.action,
             "resource_type": item.resource_type, "resource_id": item.resource_id,
             "created_at": item.created_at.isoformat(timespec="seconds")}
            for item in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200))]
