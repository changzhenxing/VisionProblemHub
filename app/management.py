"""Organization, project collaboration and evidence-based communication APIs."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import can_issue, can_person, can_project, require_issue, require_project
from .auth import authenticated_user, permissions_for
from .db import DATA_DIR, get_db
from .models import (AuditLog, Decision, Department, Feedback, FeedbackAttachment, Issue,
                     IssueCollaborator, IssueEvent, Milestone, Notification, Project,
                     ProjectMember, Team, User)

router = APIRouter(prefix="/api")
FEEDBACK_KINDS = {"认可", "建议", "追问", "协助"}
VISIBILITIES = {"project", "participants", "self_manager", "management"}
PRIVATE_FILES = DATA_DIR / "private_feedback"
PRIVATE_FILES.mkdir(parents=True, exist_ok=True)
MAX_FEEDBACK_FILE = 20 * 1024 * 1024


def actor(request: Request, db: Session) -> User:
    return authenticated_user(request, db)


def require_action(request: Request, permission: str):
    if permission not in request.state.permissions:
        raise HTTPException(403, "当前角色没有此操作权限")


def audit(db: Session, user_id: int, action: str, resource_type: str, resource_id: int | None,
          before: dict | None = None, after: dict | None = None):
    db.add(AuditLog(actor_id=user_id, action=action, resource_type=resource_type, resource_id=resource_id,
                    before_json=json.dumps(before, ensure_ascii=False) if before else None,
                    after_json=json.dumps(after, ensure_ascii=False) if after else None))


@router.get("/org/departments")
def list_departments(request: Request, db: Session = Depends(get_db)):
    actor(request, db)
    return [{"id": item.id, "name": item.name} for item in db.scalars(select(Department).order_by(Department.name))]


@router.post("/org/departments")
def add_department(payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "org.manage")
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 100: raise HTTPException(400, "部门名称须为 1 到 100 个字符")
    if db.scalar(select(Department.id).where(Department.name == name)):
        raise HTTPException(409, "部门已存在")
    item = Department(name=name); db.add(item); db.flush()
    audit(db, user.id, "创建部门", "department", item.id, after={"name": name})
    db.commit()
    return {"id": item.id, "name": name}


@router.get("/org/teams")
def list_teams(request: Request, db: Session = Depends(get_db)):
    actor(request, db)
    return [{"id": team.id, "name": team.name, "department_id": team.department_id}
            for team in db.scalars(select(Team).order_by(Team.id))]


@router.post("/org/teams")
def add_team(payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "org.manage")
    name = str(payload.get("name", "")).strip()
    department_id = payload.get("department_id")
    if not name or len(name) > 100 or type(department_id) is not int or not db.get(Department, department_id):
        raise HTTPException(400, "团队名称或部门非法")
    if db.scalar(select(Team.id).where(Team.name == name, Team.department_id == department_id)):
        raise HTTPException(409, "此部门下已有同名团队")
    team = Team(name=name, department_id=department_id); db.add(team); db.flush()
    audit(db, user.id, "创建团队", "team", team.id, after={"name": name, "department_id": department_id})
    db.commit()
    return {"id": team.id, "name": name, "department_id": department_id}


@router.get("/projects/{project_id}/members")
def project_members(project_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    require_project(db, user, db.get(Project, project_id))
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
                      .where(ProjectMember.project_id == project_id).order_by(User.name)).all()
    return [{"user_id": member.user_id, "name": person.name, "member_role": member.member_role}
            for member, person in rows]


@router.put("/projects/{project_id}/members/{user_id}")
def put_project_member(project_id: int, user_id: int, payload: dict, request: Request,
                       db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "org.manage")
    project = require_project(db, user, db.get(Project, project_id), "org.manage")
    target = db.get(User, user_id)
    if not target or not target.active: raise HTTPException(400, "成员不存在或已停用")
    member_role = str(payload.get("member_role", "成员")).strip()
    if member_role not in {"负责人", "成员", "专家", "协同"}:
        raise HTTPException(400, "成员职责非法")
    member = db.get(ProjectMember, (project_id, user_id))
    before = {"member_role": member.member_role} if member else None
    if member:
        member.member_role = member_role
    else:
        db.add(ProjectMember(project_id=project_id, user_id=user_id, member_role=member_role))
    audit(db, user.id, "配置项目成员", "project", project.id, before, {"user_id": user_id, "member_role": member_role})
    db.commit()
    return {"user_id": user_id, "member_role": member_role}


@router.delete("/projects/{project_id}/members/{user_id}")
def remove_project_member(project_id: int, user_id: int, request: Request,
                          db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "org.manage")
    project = require_project(db, user, db.get(Project, project_id), "org.manage")
    if project.manager_id == user_id:
        raise HTTPException(400, "先更换项目负责人")
    member = db.get(ProjectMember, (project_id, user_id))
    if not member: raise HTTPException(404, "项目成员不存在")
    db.delete(member)
    audit(db, user.id, "移除项目成员", "project", project_id, before={"user_id": user_id})
    db.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/milestones")
def list_milestones(project_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    require_project(db, user, db.get(Project, project_id))
    return [milestone_dict(item) for item in db.scalars(select(Milestone)
            .where(Milestone.project_id == project_id).order_by(Milestone.due_date, Milestone.id))]


def milestone_dict(item: Milestone):
    return {"id": item.id, "project_id": item.project_id, "title": item.title,
            "due_date": item.due_date.isoformat(), "completed_at": item.completed_at.isoformat() if item.completed_at else None}


@router.post("/projects/{project_id}/milestones")
def add_milestone(project_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "milestones.write")
    require_project(db, user, db.get(Project, project_id), "milestones.write")
    title = str(payload.get("title", "")).strip()
    if not title or len(title) > 160: raise HTTPException(400, "里程碑标题须为 1 到 160 个字符")
    try: due_date = date.fromisoformat(str(payload.get("due_date", "")))
    except ValueError: raise HTTPException(400, "日期非法")
    item = Milestone(project_id=project_id, title=title, due_date=due_date)
    db.add(item); db.flush()
    audit(db, user.id, "创建里程碑", "milestone", item.id, after=milestone_dict(item))
    db.commit()
    return milestone_dict(item)


@router.patch("/milestones/{milestone_id}")
def update_milestone(milestone_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "milestones.write")
    item = db.get(Milestone, milestone_id)
    if not item: raise HTTPException(404, "里程碑不存在")
    require_project(db, user, db.get(Project, item.project_id), "milestones.write")
    before = milestone_dict(item)
    if "title" in payload:
        title = str(payload["title"]).strip()
        if not title or len(title) > 160: raise HTTPException(400, "标题非法")
        item.title = title
    if "due_date" in payload:
        try: item.due_date = date.fromisoformat(str(payload["due_date"]))
        except ValueError: raise HTTPException(400, "日期非法")
    if "completed" in payload:
        if type(payload["completed"]) is not bool: raise HTTPException(400, "完成状态非法")
        item.completed_at = datetime.now() if payload["completed"] else None
    audit(db, user.id, "修改里程碑", "milestone", item.id, before, milestone_dict(item))
    db.commit()
    return milestone_dict(item)


@router.get("/issues/{issue_id}/collaborators")
def issue_collaborators(issue_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    require_issue(db, user, db.get(Issue, issue_id))
    rows = db.execute(select(IssueCollaborator, User).join(User, User.id == IssueCollaborator.user_id)
                      .where(IssueCollaborator.issue_id == issue_id)).all()
    return [{"user_id": item.user_id, "name": person.name} for item, person in rows]


@router.put("/issues/{issue_id}/collaborators")
def set_issue_collaborators(issue_id: int, payload: list[int], request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "issues.write")
    issue = require_issue(db, user, db.get(Issue, issue_id), "issues.write")
    if len(payload) > 20 or any(type(value) is not int for value in payload):
        raise HTTPException(400, "协同人员非法")
    for user_id in set(payload):
        target = db.get(User, user_id)
        if not target or not target.active: raise HTTPException(400, "协同人员不存在或已停用")
    before = [item.user_id for item in db.scalars(select(IssueCollaborator).where(IssueCollaborator.issue_id == issue_id))]
    for item in db.scalars(select(IssueCollaborator).where(IssueCollaborator.issue_id == issue_id)):
        db.delete(item)
    db.flush()
    for user_id in set(payload):
        db.add(IssueCollaborator(issue_id=issue_id, user_id=user_id))
        if not db.get(ProjectMember, (issue.project_id, user_id)):
            db.add(ProjectMember(project_id=issue.project_id, user_id=user_id, member_role="协同"))
    audit(db, user.id, "配置协同人员", "issue", issue_id, {"user_ids": before}, {"user_ids": sorted(set(payload))})
    db.commit()
    return {"user_ids": sorted(set(payload))}


def feedback_visible(db: Session, user: User, item: Feedback) -> bool:
    if item.visibility == "project":
        return can_issue(db, user, db.get(Issue, item.issue_id))
    if user.id == item.author_id:
        return True
    if item.visibility == "participants":
        return (user.id == item.recipient_id or
                user.id == db.get(Issue, item.issue_id).owner_id or
                db.get(IssueCollaborator, (item.issue_id, user.id)) is not None)
    subject = db.get(User, item.recipient_id)
    if item.visibility == "self_manager":
        return user.id == subject.id or can_person(db, user, subject, sensitive=True)
    return can_person(db, user, subject, manage=True)


def feedback_dict(db: Session, item: Feedback):
    author = db.get(User, item.author_id); recipient = db.get(User, item.recipient_id)
    files = db.scalars(select(FeedbackAttachment).where(FeedbackAttachment.feedback_id == item.id)).all()
    return {"id": item.id, "issue_id": item.issue_id, "event_id": item.event_id,
            "author_id": item.author_id, "author_name": author.name if author else "",
            "recipient_id": item.recipient_id, "recipient_name": recipient.name if recipient else "",
            "kind": item.kind, "content": item.content, "visibility": item.visibility,
            "created_at": item.created_at.isoformat(timespec="minutes"),
            "attachments": [{"id": file.id, "name": file.original_name, "mime_type": file.mime_type,
                             "url": f"/api/feedback-files/{file.id}"} for file in files]}


@router.get("/issues/{issue_id}/feedback")
def list_feedback(issue_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    require_issue(db, user, db.get(Issue, issue_id))
    items = db.scalars(select(Feedback).where(Feedback.issue_id == issue_id).order_by(Feedback.created_at)).all()
    visible = [item for item in items if feedback_visible(db, user, item)]
    if any(item.visibility in {"self_manager", "management"} for item in visible):
        audit(db, user.id, "查看私密反馈", "issue", issue_id); db.commit()
    return [feedback_dict(db, item) for item in visible]


@router.post("/issues/{issue_id}/feedback")
def add_feedback(issue_id: int, request: Request, kind: str = Form(...), content: str = Form(...),
                 recipient_id: int | None = Form(None), visibility: str = Form("project"),
                 event_id: int | None = Form(None), files: list[UploadFile] | None = File(None),
                 db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "feedback.write")
    issue = require_issue(db, user, db.get(Issue, issue_id), "feedback.write")
    content = content.strip()
    if kind not in FEEDBACK_KINDS or not content or len(content) > 5000 or visibility not in VISIBILITIES:
        raise HTTPException(400, "反馈类型、内容或可见范围非法")
    recipient_id = recipient_id or issue.owner_id
    recipient = db.get(User, recipient_id)
    if not recipient or not recipient.active: raise HTTPException(400, "接收人不存在或已停用")
    if event_id:
        event = db.get(IssueEvent, event_id)
        if not event or event.issue_id != issue_id: raise HTTPException(400, "反馈来源不属于此问题")
    if visibility in {"self_manager", "management"} and not can_person(db, user, recipient, manage=True):
        raise HTTPException(403, "无权创建私密管理反馈")
    uploads = files or []
    if len(uploads) > 5: raise HTTPException(400, "最多上传五个附件")
    item = Feedback(issue_id=issue_id, event_id=event_id, author_id=user.id, recipient_id=recipient_id,
                    kind=kind, content=content, visibility=visibility)
    db.add(item); db.flush()
    for upload in uploads:
        data = upload.file.read(MAX_FEEDBACK_FILE + 1)
        if len(data) > MAX_FEEDBACK_FILE: raise HTTPException(413, "单个附件不能超过 20 MB")
        stored = uuid.uuid4().hex + Path(upload.filename or "file").suffix[:16]
        (PRIVATE_FILES / stored).write_bytes(data)
        db.add(FeedbackAttachment(feedback_id=item.id, original_name=(upload.filename or "file")[:255],
                                  stored_name=stored, mime_type=(upload.content_type or "application/octet-stream")[:120],
                                  size_bytes=len(data)))
    if recipient.id != user.id:
        db.add(Notification(user_id=recipient.id, kind="管理反馈", issue_id=issue_id,
                            content=f"{user.name}对问题给出{kind}：{content[:80]}"))
    audit(db, user.id, "发表反馈", "feedback", item.id, after={"kind": kind, "recipient_id": recipient_id,
                                                               "visibility": visibility, "issue_id": issue_id})
    db.commit()
    return feedback_dict(db, item)


@router.get("/feedback-files/{file_id}")
def get_feedback_file(file_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db)
    file = db.get(FeedbackAttachment, file_id)
    feedback = db.get(Feedback, file.feedback_id) if file else None
    if not feedback or not feedback_visible(db, user, feedback): raise HTTPException(404, "附件不可访问")
    path = PRIVATE_FILES / file.stored_name
    if not path.is_file(): raise HTTPException(404, "附件不存在")
    if feedback.visibility in {"self_manager", "management"}:
        audit(db, user.id, "下载私密反馈附件", "feedback_attachment", file_id); db.commit()
    return FileResponse(path, media_type=file.mime_type, filename=file.original_name)


def decision_visible(db: Session, user: User, item: Decision) -> bool:
    if item.visibility == "project": return can_issue(db, user, db.get(Issue, item.issue_id))
    if user.id == item.author_id or user.id == item.owner_id: return True
    if item.visibility == "participants":
        return db.get(IssueCollaborator, (item.issue_id, user.id)) is not None
    subject = db.get(User, item.owner_id or db.get(Issue, item.issue_id).owner_id)
    if item.visibility == "self_manager": return can_person(db, user, subject, sensitive=True)
    return can_person(db, user, subject, manage=True)


def decision_dict(db: Session, item: Decision):
    return {"id": item.id, "issue_id": item.issue_id, "author_id": item.author_id,
            "author_name": db.get(User, item.author_id).name, "fact": item.fact,
            "judgment": item.judgment, "decision": item.decision, "commitment": item.commitment,
            "owner_id": item.owner_id, "due_date": item.due_date.isoformat() if item.due_date else None,
            "visibility": item.visibility, "created_at": item.created_at.isoformat(timespec="minutes")}


@router.get("/issues/{issue_id}/decisions")
def list_decisions(issue_id: int, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); require_issue(db, user, db.get(Issue, issue_id))
    items = db.scalars(select(Decision).where(Decision.issue_id == issue_id).order_by(Decision.created_at)).all()
    visible = [item for item in items if decision_visible(db, user, item)]
    if any(item.visibility in {"self_manager", "management"} for item in visible):
        audit(db, user.id, "查看私密结论", "issue", issue_id); db.commit()
    return [decision_dict(db, item) for item in visible]


@router.post("/issues/{issue_id}/decisions")
def add_decision(issue_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    user = actor(request, db); require_action(request, "feedback.write")
    issue = require_issue(db, user, db.get(Issue, issue_id), "feedback.write")
    visibility = payload.get("visibility", "project")
    if visibility not in VISIBILITIES: raise HTTPException(400, "可见范围非法")
    owner_id = payload.get("owner_id") or issue.owner_id
    owner = db.get(User, owner_id) if type(owner_id) is int else None
    if not owner or not owner.active: raise HTTPException(400, "责任人非法")
    if visibility in {"self_manager", "management"} and not can_person(db, user, owner, manage=True):
        raise HTTPException(403, "无权创建私密结论")
    fields = {key: str(payload.get(key, "")).strip() for key in ("fact", "judgment", "decision", "commitment")}
    if not any(fields.values()) or any(len(value) > 3000 for value in fields.values()):
        raise HTTPException(400, "至少填写一个结论字段，每项不超过 3000 字")
    try: due = date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None
    except ValueError: raise HTTPException(400, "日期非法")
    item = Decision(issue_id=issue_id, author_id=user.id, owner_id=owner_id, due_date=due,
                    visibility=visibility, **fields)
    db.add(item); db.flush()
    if owner_id != user.id and fields["commitment"]:
        db.add(Notification(user_id=owner_id, kind="协作承诺", issue_id=issue_id,
                            content=f"{user.name}记录了待办承诺：{fields['commitment'][:80]}"))
    audit(db, user.id, "记录沟通结论", "decision", item.id, after={"issue_id": issue_id,
                                                              "owner_id": owner_id, "visibility": visibility})
    db.commit()
    return decision_dict(db, item)
