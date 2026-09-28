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
from .models import LoginSession, Role, User

COOKIE_NAME = "vph_session"
SESSION_HOURS = 12
PERMISSIONS = {
    "users.manage": "管理用户",
    "roles.manage": "管理角色",
    "projects.write": "创建和修改项目及项目复盘",
    "issues.write": "创建和处理问题及问题复盘",
    "knowledge.write": "修订知识案例",
}
SYSTEM_ROLES = (
    ("管理员", "管理用户、角色及全部业务数据", list(PERMISSIONS)),
    ("项目负责人", "管理项目、问题和知识", ["projects.write", "issues.write", "knowledge.write"]),
    ("团队成员", "记录和处理问题", ["issues.write"]),
    ("只读成员", "查看项目、问题和知识", []),
)


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
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for name, description, permissions in SYSTEM_ROLES:
            if not db.scalar(select(Role).where(Role.name == name)):
                db.add(Role(name=name, description=description, permissions_json=json.dumps(permissions), is_system=True))
        db.flush()
        roles = {role.name: role for role in db.scalars(select(Role)).all()}
        users = db.scalars(select(User).where(User.role_id.is_(None)).order_by(User.id)).all()
        for user in users:
            name = "管理员" if user.name == "管理员" else user.role
            if name not in roles:
                name = "项目负责人" if user.role == "团队负责人" else "团队成员"
            user.role_id = roles[name].id
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
    if not user.assigned_role:
        return set()
    try:
        return set(json.loads(user.assigned_role.permissions_json)) & PERMISSIONS.keys()
    except (ValueError, TypeError):
        return set()


def user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "role_id": user.role_id,
        "role": user.assigned_role.name if user.assigned_role else user.role,
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
    if path.startswith("/api/projects"):
        return "projects.write"
    if path.startswith("/api/issues"):
        return "issues.write"
    if path.startswith("/api/knowledge"):
        return "knowledge.write"
    return None
