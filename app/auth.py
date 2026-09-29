from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine
from .models import LoginSession, Role, User, UserRole, Project, ProjectMember, Issue, IssueEvent, Team

COOKIE_NAME = "vph_session"
SESSION_HOURS = 12
PERMISSIONS = {
    "users.manage": "管理用户",
    "roles.manage": "管理角色",
    "projects.write": "创建和修改项目及项目复盘",
    "issues.write": "创建和处理问题及问题复盘",
    "knowledge.write": "修订知识案例",
    "feedback.write": "发表问题反馈",
    "people.read": "查看人员工作与能力证据",
    "people.manage": "管理沟通与成长记录",
    "org.manage": "管理组织与项目成员",
    "milestones.write": "管理里程碑",
    "reports.write": "确认周报",
    "audit.read": "查看审计记录",
}
SYSTEM_ROLES = (
    ("管理员", "管理用户、角色及全部业务数据", list(PERMISSIONS)),
    ("部门负责人", "部门项目与人员管理", ["projects.write", "issues.write", "feedback.write", "people.read", "people.manage", "org.manage", "milestones.write", "reports.write"]),
    ("团队主管", "团队项目与人员培养", ["projects.write", "issues.write", "feedback.write", "people.read", "people.manage", "milestones.write", "reports.write"]),
    ("项目负责人", "管理项目、问题和知识", ["projects.write", "issues.write", "knowledge.write", "feedback.write", "people.read", "milestones.write", "reports.write"]),
    ("技术负责人", "技术方案与问题决策", ["issues.write", "feedback.write", "knowledge.write", "people.read", "reports.write"]),
    ("团队成员", "记录和处理问题", ["issues.write", "feedback.write", "reports.write"]),
    ("专家", "跨项目技术支持", ["issues.write", "feedback.write", "knowledge.write", "people.read", "reports.write"]),
    ("知识管理员", "审核和整理知识", ["knowledge.write", "people.read", "reports.write"]),
    ("只读成员", "查看项目、问题和知识", []),
)
SCOPES = {"self", "project", "team", "department", "all"}


def ensure_auth_schema():
    """Add authentication columns to databases created before user management."""
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    with engine.begin() as conn:
        if "role_id" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES roles(id)"))
        if "password_hash" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)"))
        if "active" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1"))
        if "team_id" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN team_id INTEGER REFERENCES teams(id)"))
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for name, description, permissions in SYSTEM_ROLES:
            role = db.scalar(select(Role).where(Role.name == name))
            if not role:
                db.add(Role(name=name, description=description, permissions_json=json.dumps(permissions), is_system=True))
            elif role.is_system:
                role.description = description
                role.permissions_json = json.dumps(permissions)
        db.flush()
        roles = {role.name: role for role in db.scalars(select(Role)).all()}
        users = db.scalars(select(User).where(User.role_id.is_(None)).order_by(User.id)).all()
        for user in users:
            name = "管理员" if user.name == "管理员" else user.role
            if name not in roles:
                name = "项目负责人" if user.role == "团队负责人" else "团队成员"
            user.role_id = roles[name].id
        db.flush()
        for user in db.scalars(select(User).order_by(User.id)):
            if not db.scalar(select(UserRole.id).where(UserRole.user_id == user.id).limit(1)):
                db.add(UserRole(user_id=user.id, role_id=user.role_id,
                                scope="all" if user.name == "管理员" else "self"))
        memberships = set(db.execute(select(ProjectMember.project_id, ProjectMember.user_id)).all())
        def add_member(project_id: int, user_id: int, member_role: str = "成员"):
            if (project_id, user_id) not in memberships:
                db.add(ProjectMember(project_id=project_id, user_id=user_id, member_role=member_role))
                memberships.add((project_id, user_id))
        for project in db.scalars(select(Project)):
            add_member(project.id, project.manager_id, "负责人")
        for issue in db.scalars(select(Issue)):
            for user_id in {issue.owner_id, issue.created_by_id}:
                add_member(issue.project_id, user_id)
        for event in db.scalars(select(IssueEvent).where(IssueEvent.actor_id.is_not(None))):
            issue = db.get(Issue, event.issue_id)
            if issue:
                add_member(issue.project_id, event.actor_id)
        db.commit()


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 128:
        raise HTTPException(400, "密码长度须为 12 到 128 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, rounds, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def setup_required(db: Session) -> bool:
    return db.scalar(select(User.id).where(User.password_hash.is_not(None)).limit(1)) is None


def permissions_for(user: User) -> set[str]:
    with SessionLocal() as db:
        roles = db.scalars(select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)).all()
        if not roles and user.assigned_role:
            roles = [user.assigned_role]
        result = set()
        for role in roles:
            try:
                result.update(json.loads(role.permissions_json))
            except (ValueError, TypeError):
                pass
        return result & PERMISSIONS.keys()


def user_dict(user: User) -> dict:
    with SessionLocal() as db:
        assignments = db.execute(select(UserRole, Role).join(Role, UserRole.role_id == Role.id)
                                 .where(UserRole.user_id == user.id).order_by(UserRole.id)).all()
    return {
        "id": user.id,
        "name": user.name,
        "role_id": user.role_id,
        "role": user.assigned_role.name if user.assigned_role else user.role,
        "roles": [{"id": assignment.id, "role_id": role.id, "name": role.name,
                   "scope": assignment.scope, "scope_id": assignment.scope_id} for assignment, role in assignments],
        "team_id": user.team_id,
        "active": user.active,
        "has_password": bool(user.password_hash),
        "permissions": sorted(permissions_for(user)),
    }


def role_dict(role: Role, user_count: int = 0) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "permissions": json.loads(role.permissions_json),
        "is_system": role.is_system,
        "user_count": user_count,
    }


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                        expires_at=datetime.now() + timedelta(hours=SESSION_HOURS)))
    db.commit()
    return token


def session_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest())
    if not session or session.expires_at <= datetime.now():
        return None
    user = db.get(User, session.user_id)
    return user if user and user.active and user.password_hash else None


def authenticated_user(request: Request, db: Session) -> User:
    user_id = getattr(request.state, "user_id", None)
    user = db.get(User, user_id) if user_id else None
    if not user or not user.active:
        raise HTTPException(401, "请先登录")
    return user


def required_permission(path: str, method: str) -> str | None:
    if path.startswith("/api/admin/roles") or path == "/api/admin/permissions":
        return "roles.manage"
    if path.startswith("/api/admin/users") or (path == "/api/users" and method != "GET"):
        return "users.manage"
    if method in {"GET", "HEAD", "OPTIONS"}:
        return None
    if path.startswith("/api/org/") or (path.startswith("/api/projects/") and "/members" in path):
        return "org.manage"
    if path.startswith("/api/milestones/") or (path.startswith("/api/projects/") and "/milestones" in path):
        return "milestones.write"
    if path.startswith("/api/issues/") and (path.endswith("/feedback") or path.endswith("/decisions")):
        return "feedback.write"
    if path.startswith("/api/projects"):
        return "projects.write"
    if path.startswith("/api/issues"):
        return "issues.write"
    if path.startswith("/api/knowledge"):
        return "knowledge.write"
    return None
