from __future__ import annotations
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict
import json
import hashlib
import re
from fastapi import FastAPI, Depends, HTTPException, Query, Form, UploadFile, File, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session, selectinload, joinedload

from .db import Base, engine, get_db, DATA_DIR, SessionLocal
from .models import User, Role, UserRole, Department, Team, LoginSession, Project, ProjectMember, ProjectEvent, Issue, IssueEvent, Attachment, IssueRetrospective, ProjectRetrospective, KnowledgeCase
from .auth import (COOKIE_NAME, SESSION_HOURS, PERMISSIONS, ensure_auth_schema, hash_password, verify_password,
                   setup_required, permissions_for, user_dict, role_dict, create_session, session_user,
                   authenticated_user, required_permission, SCOPES)
from .access import can_project, can_issue, can_person, require_project, require_issue, grants
from .management import router as management_router, audit
from .people import router as people_router
from .schemas import *
from .services import (
    is_delayed, delay_days, project_health, add_event, save_attachment,
    ensure_issue_retro, ensure_project_retro, ensure_knowledge_case,
    loads_list, dumps, UPLOAD_DIR, RETRO_FIELDS, PROJECT_RETRO_FIELDS, KNOWLEDGE_FIELDS,
)

Base.metadata.create_all(bind=engine)
ensure_auth_schema()
app=FastAPI(title="以问题驱动的工业视觉项目管理与知识沉淀平台", version="2.0.0")
STATIC_DIR=Path(__file__).resolve().parent/"static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.include_router(management_router)
app.include_router(people_router)

@app.middleware("http")
async def authentication(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") and not path.startswith("/uploads/"):
        return await call_next(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail": "请求来源不匹配"}, status_code=403)
    if path in {"/api/auth/status", "/api/auth/setup", "/api/auth/login"}:
        return await call_next(request)
    with SessionLocal() as db:
        user = session_user(db, request.cookies.get(COOKIE_NAME))
        if not user:
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        request.state.user_id = user.id
        request.state.permissions = permissions_for(user)
        permission = required_permission(path, request.method)
        role_catalog = (path.startswith("/api/admin/roles") or path == "/api/admin/permissions") and request.method == "GET"
        if role_catalog and not request.state.permissions.intersection({"users.manage", "roles.manage"}):
            return JSONResponse({"detail": "当前角色没有此操作权限"}, status_code=403)
        if permission and permission not in request.state.permissions and not role_catalog:
            return JSONResponse({"detail": "当前角色没有此操作权限"}, status_code=403)
        project_match=re.match(r"^/api/projects/(\d+)(?:/|$)",path)
        issue_match=re.match(r"^/api/issues/(\d+)(?:/|$)",path)
        knowledge_match=re.match(r"^/api/knowledge/(\d+)(?:/|$)",path)
        if project_match:
            project=db.get(Project,int(project_match.group(1)))
            if not project or not can_project(db,user,project,permission):
                return JSONResponse({"detail":"项目不可访问"},status_code=403 if permission else 404)
        if issue_match:
            issue=db.get(Issue,int(issue_match.group(1)))
            if not issue or not can_issue(db,user,issue,permission):
                return JSONResponse({"detail":"问题不可访问"},status_code=403 if permission else 404)
        if knowledge_match:
            case=db.get(KnowledgeCase,int(knowledge_match.group(1)))
            issue=db.get(Issue,case.issue_id) if case else None
            if not issue or not can_issue(db,user,issue,permission):
                return JSONResponse({"detail":"知识案例不可访问"},status_code=403 if permission else 404)
        if path.startswith("/uploads/"):
            attachment=db.scalar(select(Attachment).where(Attachment.relative_path=="uploads/"+path.removeprefix("/uploads/")))
            issue=db.get(Issue,attachment.event.issue_id) if attachment else None
            if not issue or not can_issue(db,user,issue):
                return JSONResponse({"detail":"附件不可访问"},status_code=404)
    return await call_next(request)

@app.get("/")
def root(): return FileResponse(STATIC_DIR/"index.html")

@app.get("/api/auth/status")
def auth_status(db: Session = Depends(get_db)):
    return {"setup_required": setup_required(db)}


@app.post("/api/auth/setup")
def auth_setup(payload: dict, request: Request, response: Response, db: Session = Depends(get_db)):
    if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "首次设置只能在服务器本机完成")
    if not setup_required(db):
        raise HTTPException(409, "管理员密码已设置")
    admin = db.scalar(select(User).where(User.name == "管理员")) or db.scalar(select(User).order_by(User.id))
    if not admin:
        admin = User(name="管理员", role="管理员")
        db.add(admin)
        db.flush()
    admin.role_id = db.scalar(select(Role.id).where(Role.name == "管理员"))
    admin.active = True
    admin.password_hash = hash_password(str(payload.get("password", "")))
    if not db.scalar(select(UserRole.id).where(UserRole.user_id==admin.id)):
        db.add(UserRole(user_id=admin.id,role_id=admin.role_id,scope="all"))
    db.commit()
    token = create_session(db, admin)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=SESSION_HOURS * 3600)
    return user_dict(admin)


@app.post("/api/auth/login")
def auth_login(payload: dict, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.name == str(payload.get("name", "")).strip()))
    if not user or not user.active or not verify_password(str(payload.get("password", "")), user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    token = create_session(db, user)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=SESSION_HOURS * 3600)
    return user_dict(user)


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest())
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(COOKIE_NAME, samesite="strict")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    return user_dict(authenticated_user(request, db))


@app.post("/api/auth/password")
def change_password(payload: dict, request: Request, response: Response, db: Session = Depends(get_db)):
    user = authenticated_user(request, db)
    if not verify_password(str(payload.get("current_password", "")), user.password_hash):
        raise HTTPException(400, "当前密码不正确")
    user.password_hash = hash_password(str(payload.get("new_password", "")))
    db.query(LoginSession).filter(LoginSession.user_id == user.id).delete()
    db.commit()
    token = create_session(db, user)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=SESSION_HOURS * 3600)
    return {"ok": True}

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
    return [{"id":u.id,"name":u.name,"team_id":u.team_id}
            for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.id)).all()]

@app.post("/api/users")
def create_user(payload:dict, request:Request, db:Session=Depends(get_db)):
    name=str(payload.get("name","")).strip()
    if not name: raise HTTPException(400,"姓名不能为空")
    if len(name)>80: raise HTTPException(400,"姓名不能超过 80 个字符")
    if db.scalar(select(User).where(User.name==name)): raise HTTPException(409,"用户已存在")
    role=db.get(Role,payload.get("role_id")) if type(payload.get("role_id")) is int else None
    if not role: raise HTTPException(400,"请选择有效角色")
    team_id=payload.get("team_id")
    if team_id is not None and (type(team_id) is not int or not db.get(Team,team_id)):
        raise HTTPException(400,"团队不存在")
    scope=payload.get("scope", "all" if role.name=="管理员" else "self")
    scope_id=payload.get("scope_id")
    if scope not in SCOPES or (scope in {"all","self"} and scope_id is not None):
        raise HTTPException(400,"授权范围非法")
    scope_model={"project":Project,"team":Team,"department":Department}.get(scope)
    if scope_id is not None and (type(scope_id) is not int or not db.get(scope_model,scope_id)):
        raise HTTPException(400,"授权对象不存在")
    u=User(name=name,role=role.name,role_id=role.id,team_id=team_id,
           password_hash=hash_password(str(payload.get("password",""))),active=True)
    db.add(u); db.flush()
    db.add(UserRole(user_id=u.id,role_id=role.id,scope=scope,scope_id=scope_id))
    audit(db,request.state.user_id,"创建用户","user",u.id,after={"role_id":role.id,"scope":scope,"scope_id":scope_id,"team_id":team_id})
    db.commit(); db.refresh(u)
    return user_dict(u)


@app.get("/api/admin/users")
def admin_users(db:Session=Depends(get_db)):
    return [user_dict(u) for u in db.scalars(select(User).order_by(User.id)).all()]


@app.patch("/api/admin/users/{user_id}")
def update_user(user_id:int,payload:dict,request:Request,db:Session=Depends(get_db)):
    user=db.get(User,user_id)
    if not user: raise HTTPException(404,"用户不存在")
    allowed={"name","role_id","active","password","team_id"}
    if set(payload)-allowed: raise HTTPException(400,"包含不支持的用户字段")
    before={"name":user.name,"role_id":user.role_id,"active":user.active,"team_id":user.team_id}
    if "name" in payload:
        name=str(payload["name"]).strip()
        if not name or len(name)>80: raise HTTPException(400,"姓名须为 1 到 80 个字符")
        if name!=user.name and db.scalar(select(User.id).where(User.name==name)):
            raise HTTPException(409,"用户已存在")
        user.name=name
    if "role_id" in payload:
        role=db.get(Role,payload["role_id"]) if type(payload["role_id"]) is int else None
        if not role: raise HTTPException(400,"角色不存在")
        user.role_id=role.id; user.role=role.name
        assignment=db.scalar(select(UserRole).where(UserRole.user_id==user.id).order_by(UserRole.id))
        if assignment:
            assignment.role_id=role.id
        else:
            db.add(UserRole(user_id=user.id,role_id=role.id,scope="all" if role.name=="管理员" else "self"))
    if "team_id" in payload:
        team_id=payload["team_id"]
        if team_id is not None and (type(team_id) is not int or not db.get(Team,team_id)):
            raise HTTPException(400,"团队不存在")
        user.team_id=team_id
    if "active" in payload:
        if not isinstance(payload["active"],bool): raise HTTPException(400,"状态非法")
        user.active=payload["active"]
    if "password" in payload and payload["password"]:
        user.password_hash=hash_password(str(payload["password"]))
        db.query(LoginSession).filter(LoginSession.user_id==user.id).delete()
    if user.id==request.state.user_id and not user.active:
        raise HTTPException(400,"不能停用当前登录账户")
    admin_role=db.scalar(select(Role).where(Role.name=="管理员"))
    db.flush()
    admin_count=db.scalar(select(func.count(func.distinct(User.id))).join(UserRole,UserRole.user_id==User.id)
                          .where(UserRole.role_id==admin_role.id,UserRole.scope=="all",User.active.is_(True)))
    if not admin_count: raise HTTPException(400,"必须保留至少一名启用的全局管理员")
    audit(db,request.state.user_id,"修改用户","user",user.id,before,
          {"name":user.name,"role_id":user.role_id,"active":user.active,"team_id":user.team_id,
           "password_reset":bool(payload.get("password"))})
    db.commit(); db.refresh(user)
    return user_dict(user)


@app.put("/api/admin/users/{user_id}/roles")
def set_user_roles(user_id:int,payload:list[dict],request:Request,db:Session=Depends(get_db)):
    user=db.get(User,user_id)
    if not user: raise HTTPException(404,"用户不存在")
    if not payload or len(payload)>10: raise HTTPException(400,"至少配置一个角色，最多十个")
    before=[{"role_id":item.role_id,"scope":item.scope,"scope_id":item.scope_id}
            for item in db.scalars(select(UserRole).where(UserRole.user_id==user_id))]
    validated=[]
    for item in payload:
        role_id=item.get("role_id")
        role=db.get(Role,role_id) if type(role_id) is int else None
        scope=item.get("scope")
        scope_id=item.get("scope_id")
        if not role or scope not in SCOPES or (scope in {"self","all"} and scope_id is not None):
            raise HTTPException(400,"角色或范围非法")
        scope_model={"project":Project,"team":Team,"department":Department}.get(scope)
        if scope_id is not None and (type(scope_id) is not int or not db.get(scope_model,scope_id)):
            raise HTTPException(400,"授权对象不存在")
        key=(role_id,scope,scope_id)
        if key in validated: raise HTTPException(400,"重复的角色授权")
        validated.append(key)
    db.execute(delete(UserRole).where(UserRole.user_id==user.id))
    for role_id,scope,scope_id in validated:
        db.add(UserRole(user_id=user.id,role_id=role_id,scope=scope,scope_id=scope_id))
    first_role=db.get(Role,validated[0][0]); user.role_id=first_role.id; user.role=first_role.name
    db.flush()
    admin_role=db.scalar(select(Role).where(Role.name=="管理员"))
    remaining=db.scalar(select(func.count(func.distinct(User.id))).join(UserRole,UserRole.user_id==User.id)
                        .where(UserRole.role_id==admin_role.id,UserRole.scope=="all",User.active.is_(True)))
    if not remaining: raise HTTPException(400,"必须保留至少一名启用的全局管理员")
    audit(db,request.state.user_id,"配置角色授权","user",user_id,{"roles":before},
          {"roles":[{"role_id":r,"scope":s,"scope_id":sid} for r,s,sid in validated]})
    db.commit(); db.refresh(user)
    return user_dict(user)


@app.get("/api/admin/roles")
def list_roles(db:Session=Depends(get_db)):
    roles=db.scalars(select(Role).order_by(Role.id)).all()
    return [role_dict(role,db.scalar(select(func.count(func.distinct(UserRole.user_id))).where(UserRole.role_id==role.id)) or 0) for role in roles]


@app.get("/api/admin/permissions")
def list_permissions():
    return [{"key":key,"label":label} for key,label in PERMISSIONS.items()]


def validate_role_payload(payload:dict):
    name=str(payload.get("name","")).strip()
    if not name or len(name)>40: raise HTTPException(400,"角色名称须为 1 到 40 个字符")
    description=str(payload.get("description","")).strip()
    if len(description)>200: raise HTTPException(400,"角色说明不能超过 200 个字符")
    permissions=payload.get("permissions",[])
    if not isinstance(permissions,list) or any(not isinstance(p,str) or p not in PERMISSIONS for p in permissions):
        raise HTTPException(400,"角色权限非法")
    return name,description,sorted(set(permissions))


@app.post("/api/admin/roles")
def create_role(payload:dict,request:Request,db:Session=Depends(get_db)):
    name,description,permissions=validate_role_payload(payload)
    if db.scalar(select(Role.id).where(Role.name==name)): raise HTTPException(409,"角色已存在")
    role=Role(name=name,description=description,permissions_json=json.dumps(permissions),is_system=False)
    db.add(role); db.flush()
    audit(db,request.state.user_id,"创建角色","role",role.id,after={"name":name,"permissions":permissions})
    db.commit(); db.refresh(role)
    return role_dict(role)


@app.patch("/api/admin/roles/{role_id}")
def update_role(role_id:int,payload:dict,request:Request,db:Session=Depends(get_db)):
    role=db.get(Role,role_id)
    if not role: raise HTTPException(404,"角色不存在")
    if role.is_system: raise HTTPException(400,"内置角色不可修改")
    name,description,permissions=validate_role_payload(payload)
    if name!=role.name and db.scalar(select(Role.id).where(Role.name==name)):
        raise HTTPException(409,"角色已存在")
    before={"name":role.name,"permissions":json.loads(role.permissions_json)}
    role.name=name; role.description=description; role.permissions_json=json.dumps(permissions)
    for user in db.scalars(select(User).where(User.role_id==role_id)):
        user.role=name
    audit(db,request.state.user_id,"修改角色","role",role_id,before,{"name":name,"permissions":permissions})
    db.commit(); db.refresh(role)
    return role_dict(role)


@app.delete("/api/admin/roles/{role_id}")
def delete_role(role_id:int,request:Request,db:Session=Depends(get_db)):
    role=db.get(Role,role_id)
    if not role: raise HTTPException(404,"角色不存在")
    if role.is_system: raise HTTPException(400,"内置角色不可删除")
    if db.scalar(select(UserRole.id).where(UserRole.role_id==role_id)):
        raise HTTPException(409,"请先将此角色下的用户转到其他角色")
    audit(db,request.state.user_id,"删除角色","role",role_id,before={"name":role.name})
    db.delete(role); db.commit()
    return {"ok":True}

# ---- Projects ----
@app.get("/api/projects")
def list_projects(request:Request,db:Session=Depends(get_db)):
    user=authenticated_user(request,db)
    ps=db.scalars(select(Project).options(joinedload(Project.manager),selectinload(Project.issues)).order_by(Project.planned_completion_date)).all()
    return [project_dict(p) for p in ps if can_project(db,user,p)]

@app.post("/api/projects")
def create_project(payload:ProjectCreate, request:Request, db:Session=Depends(get_db)):
    if payload.current_stage not in STAGES: raise HTTPException(400,"项目阶段非法")
    manager=db.get(User,payload.manager_id)
    if not manager or not manager.active: raise HTTPException(400,"项目负责人不存在或已停用")
    user=authenticated_user(request,db)
    allowed=any(grant.scope=="all" or (grant.scope=="self" and user.id==manager.id) or
                (grant.scope=="team" and manager.team_id==(grant.scope_id or user.team_id)) or
                (grant.scope=="department" and manager.team_id and
                 (db.get(Team,manager.team_id).department_id ==
                  (grant.scope_id or (db.get(Team,user.team_id).department_id if user.team_id else None))))
                for grant in grants(db,user,"projects.write"))
    if not allowed: raise HTTPException(403,"当前授权范围不能创建该项目")
    p=Project(**payload.model_dump()); db.add(p); db.flush()
    db.add(ProjectMember(project_id=p.id,user_id=manager.id,member_role="负责人"))
    if user.id!=manager.id:
        db.add(ProjectMember(project_id=p.id,user_id=user.id,member_role="成员"))
    db.add(ProjectEvent(project_id=p.id,actor_id=request.state.user_id,event_type="创建项目",content=f"创建项目：{p.name}"))
    db.commit(); db.refresh(p)
    return project_dict(get_project(db,p.id))

@app.patch("/api/projects/{project_id}")
def patch_project(project_id:int,payload:ProjectPatch,request:Request,db:Session=Depends(get_db)):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,"项目不存在")
    data=payload.model_dump(exclude_unset=True)
    if data.get("current_stage") and data["current_stage"] not in STAGES: raise HTTPException(400,"项目阶段非法")
    if "manager_id" in data:
        manager=db.get(User,data["manager_id"])
        if not manager or not manager.active: raise HTTPException(400,"项目负责人不存在或已停用")
    data.pop("actor_id",None)
    actor_id=request.state.user_id
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
    if any(field=="manager_id" for field,_,_ in changes) and not db.get(ProjectMember,(p.id,p.manager_id)):
        db.add(ProjectMember(project_id=p.id,user_id=p.manager_id,member_role="负责人"))
    if p.current_stage=="验收关闭" and not p.actual_completion_date: p.actual_completion_date=date.today()
    elif p.current_stage!="验收关闭": p.actual_completion_date=None
    db.commit(); db.expire_all()
    p=get_project(db,project_id); ensure_project_retro(db,p); db.commit()
    return project_dict(p)|{"meaningful_changes":len(changes)}

@app.get("/api/projects/{project_id}")
def project_detail(project_id:int,request:Request,db:Session=Depends(get_db)):
    p=get_project(db,project_id)
    user=authenticated_user(request,db)
    return project_dict(p)|{"issues":[issue_brief(i) for i in p.issues if can_issue(db,user,i)],
                            "events":[project_event_dict(e) for e in p.events]}

# ---- Issues ----
@app.get("/api/issues")
def list_issues(request:Request,project_id:int|None=None,owner_id:int|None=None,status:str|None=None,priority:str|None=None,issue_type:str|None=None,
                delayed_only:bool=False,q:str|None=None,db:Session=Depends(get_db)):
    stmt=select(Issue).options(joinedload(Issue.project),joinedload(Issue.owner)).order_by(Issue.planned_close_date,Issue.id)
    if project_id: stmt=stmt.where(Issue.project_id==project_id)
    if owner_id: stmt=stmt.where(Issue.owner_id==owner_id)
    if status: stmt=stmt.where(Issue.status==status)
    if priority: stmt=stmt.where(Issue.priority==priority)
    if issue_type: stmt=stmt.where(Issue.issue_type==issue_type)
    if q: stmt=stmt.where(Issue.description.contains(q))
    user=authenticated_user(request,db)
    xs=[issue for issue in db.scalars(stmt).all() if can_issue(db,user,issue)]
    if delayed_only: xs=[i for i in xs if is_delayed(i)]
    return [issue_brief(i) for i in xs]

@app.post("/api/issues")
def create_issue(payload:IssueCreate,request:Request,db:Session=Depends(get_db)):
    if payload.issue_type not in ISSUE_TYPES or payload.priority not in PRIORITIES or payload.status not in ISSUE_STATUSES: raise HTTPException(400,"问题字段非法")
    project=db.get(Project,payload.project_id)
    if not project: raise HTTPException(400,"项目不存在")
    user=authenticated_user(request,db)
    if not can_project(db,user,project,"issues.write"): raise HTTPException(403,"不属于此项目或无权创建问题")
    owner=db.get(User,payload.owner_id)
    if not owner or not owner.active: raise HTTPException(400,"Owner不存在或已停用")
    data=payload.model_dump(); data["created_by_id"]=request.state.user_id
    i=Issue(**data); db.add(i); db.flush()
    for member_id in {payload.owner_id,request.state.user_id}:
        if not db.get(ProjectMember,(project.id,member_id)):
            db.add(ProjectMember(project_id=project.id,user_id=member_id))
    add_event(db,i,request.state.user_id,"创建问题",payload.description,metadata={"issue_type":payload.issue_type,"priority":payload.priority,"owner_id":payload.owner_id})
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
def patch_issue(issue_id:int,payload:IssuePatch,request:Request,db:Session=Depends(get_db)):
    i=get_issue(db,issue_id); data=payload.model_dump(exclude_unset=True); data.pop("actor_id",None); actor=request.state.user_id
    if data.get("issue_type") and data["issue_type"] not in ISSUE_TYPES: raise HTTPException(400,"问题类型非法")
    if data.get("priority") and data["priority"] not in PRIORITIES: raise HTTPException(400,"优先级非法")
    if data.get("status") and data["status"] not in ISSUE_STATUSES: raise HTTPException(400,"问题状态非法")
    if "owner_id" in data:
        owner=db.get(User,data["owner_id"])
        if not owner or not owner.active: raise HTTPException(400,"Owner不存在或已停用")
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
    if any(field=="owner_id" for field,_,_ in changes) and not db.get(ProjectMember,(i.project_id,i.owner_id)):
        db.add(ProjectMember(project_id=i.project_id,user_id=i.owner_id))
    db.commit(); db.expire_all(); i=get_issue(db,issue_id); ensure_issue_retro(db,i); p=get_project(db,i.project_id); ensure_project_retro(db,p); db.commit()
    return issue_brief(i)|{"meaningful_changes":len(changes)}

@app.post("/api/issues/{issue_id}/creation-attachments")
def add_creation_attachments(issue_id:int,request:Request,actor_id:int=Form(...),attachment_role:str=Form("问题证据"),files:list[UploadFile]=File(...),db:Session=Depends(get_db)):
    actor_id=request.state.user_id
    i=get_issue(db,issue_id)
    e=next((e for e in i.events if e.event_type=="创建问题"),None)
    if not e: e=add_event(db,i,actor_id,"进展反馈","补充问题创建资料")
    for f in files: save_attachment(db,e,f,attachment_role,actor_id)
    event_id=e.id
    db.commit(); db.expire_all(); i=get_issue(db,issue_id); ensure_issue_retro(db,i); db.commit(); db.expire_all(); i=get_issue(db,issue_id)
    return {"attachments":[attachment_dict(a) for a in next(x for x in i.events if x.id==event_id).attachments]}

@app.post("/api/issues/{issue_id}/events")
def create_issue_event(issue_id:int,request:Request,actor_id:int=Form(...),event_type:str=Form(...),content:str=Form(""),outcome:str|None=Form(None),
                       attachment_role:str=Form("其他"),files:list[UploadFile]|None=File(None),db:Session=Depends(get_db)):
    actor_id=request.state.user_id
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
def patch_issue_retro(issue_id:int,payload:ManualRetrospectivePatch,request:Request,db:Session=Depends(get_db)):
    i=get_issue(db,issue_id); r=ensure_issue_retro(db,i)
    locked=set(loads_list(r.locked_fields_json)); changed={}
    for field,val in payload.values.items():
        if field not in RETRO_FIELDS: continue
        old=getattr(r,field); setattr(r,field,val); locked.add(field); changed[field]={"before":old,"after":val}
    r.locked_fields_json=dumps(sorted(locked))
    if payload.confirm: r.confirmed_by_id=request.state.user_id; r.confirmed_at=datetime.now()
    add_event(db,i,request.state.user_id,"复盘人工修订",f"人工修订复盘字段：{', '.join(changed.keys())}",metadata={"changes":changed,"confirm":payload.confirm})
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
def patch_project_retro(project_id:int,payload:ManualRetrospectivePatch,request:Request,db:Session=Depends(get_db)):
    p=get_project(db,project_id); r=ensure_project_retro(db,p); locked=set(loads_list(r.locked_fields_json))
    for field,val in payload.values.items():
        if field in PROJECT_RETRO_FIELDS: setattr(r,field,val); locked.add(field)
    r.locked_fields_json=dumps(sorted(locked))
    if payload.confirm: r.confirmed_by_id=request.state.user_id; r.confirmed_at=datetime.now()
    db.add(ProjectEvent(project_id=project_id,actor_id=request.state.user_id,event_type="项目复盘人工修订",content=f"人工修订项目复盘字段：{', '.join(payload.values.keys())}"))
    db.commit(); return project_retro_dict(r)

# ---- Knowledge ----
@app.get("/api/knowledge")
def list_knowledge(request:Request,q:str|None=None,issue_type:str|None=None,confidence_state:str|None=None,project_id:int|None=None,db:Session=Depends(get_db)):
    user=authenticated_user(request,db)
    stmt=(select(KnowledgeCase,Issue).join(Issue,KnowledgeCase.issue_id==Issue.id).options(joinedload(Issue.project)).order_by(KnowledgeCase.updated_at.desc()))
    if issue_type: stmt=stmt.where(Issue.issue_type==issue_type)
    if confidence_state: stmt=stmt.where(KnowledgeCase.confidence_state==confidence_state)
    if project_id: stmt=stmt.where(Issue.project_id==project_id)
    rows=db.execute(stmt).all(); out=[]
    for k,i in rows:
        if not can_issue(db,user,i): continue
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
def patch_knowledge(case_id:int,payload:KnowledgePatch,request:Request,db:Session=Depends(get_db)):
    k=db.get(KnowledgeCase,case_id)
    if not k: raise HTTPException(404,"知识案例不存在")
    locked=set(loads_list(k.locked_fields_json)); changed=[]
    for field,val in payload.values.items():
        if field not in KNOWLEDGE_FIELDS: continue
        if field=="confidence_state" and val not in KNOWLEDGE_STATES: raise HTTPException(400,"可信度状态非法")
        setattr(k,field,val); locked.add(field); changed.append(field)
    k.locked_fields_json=dumps(sorted(locked)); i=get_issue(db,k.issue_id)
    add_event(db,i,request.state.user_id,"知识人工修订",f"人工修订知识字段：{', '.join(changed)}")
    db.commit(); return knowledge_dict(k,i)

@app.post("/api/knowledge/{case_id}/regenerate")
def regenerate_knowledge(case_id:int,force:bool=False,db:Session=Depends(get_db)):
    k=db.get(KnowledgeCase,case_id)
    if not k: raise HTTPException(404,"知识案例不存在")
    i=get_issue(db,k.issue_id); r=ensure_issue_retro(db,i,force=False); k=ensure_knowledge_case(db,i,r,force=force); db.commit(); return knowledge_dict(k,i)

# ---- Workbench / Stats ----
@app.get("/api/workbench")
def workbench(owner_id:int,request:Request,db:Session=Depends(get_db)):
    user=authenticated_user(request,db)
    owner=db.get(User,owner_id)
    if not owner or not can_person(db,user,owner): raise HTTPException(403,"人员工作台不可访问")
    xs=db.scalars(select(Issue).where(Issue.owner_id==owner_id,Issue.status!="已关闭").options(joinedload(Issue.project),joinedload(Issue.owner))).all()
    xs=[issue for issue in xs if can_issue(db,user,issue)]
    today=date.today(); week=today+timedelta(days=7)
    def sortkey(i): return (0 if i.priority=="紧急重要" else 1,0 if i.status=="阻塞" else 1,i.planned_close_date)
    xs=sorted(xs,key=sortkey)
    return {"counts":{"all":len(xs),"critical":sum(i.priority=="紧急重要" for i in xs),"due_week":sum(today<=i.planned_close_date<=week for i in xs),"delayed":sum(is_delayed(i) for i in xs),"blocked":sum(i.status=="阻塞" for i in xs)},
            "issues":[issue_brief(i) for i in xs]}

@app.get("/api/stats")
def stats(request:Request,days:int=30,project_id:int|None=None,db:Session=Depends(get_db)):
    user=authenticated_user(request,db)
    start=datetime.now()-timedelta(days=max(1,min(days,365)))
    stmt=select(Issue).options(joinedload(Issue.project),joinedload(Issue.owner))
    if project_id: stmt=stmt.where(Issue.project_id==project_id)
    xs=[issue for issue in db.scalars(stmt).all() if can_issue(db,user,issue)]; recent=[i for i in xs if i.created_at>=start]
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
def agent_export(request:Request,db:Session=Depends(get_db)):
    """Multimodal structured export for future RAG/Agent ingestion."""
    user=authenticated_user(request,db)
    rows=db.execute(select(KnowledgeCase,Issue).join(Issue,KnowledgeCase.issue_id==Issue.id).options(joinedload(Issue.project))).all()
    out=[]
    for k,i0 in rows:
        if not can_issue(db,user,i0): continue
        if k.confidence_state=="已废弃": continue
        i=get_issue(db,i0.id); r=ensure_issue_retro(db,i)
        out.append({"case":knowledge_dict(k,i),"issue":issue_brief(i),"retrospective":retro_dict(r),
                    "events":[event_dict(e) for e in i.events]})
    db.commit()
    return out
