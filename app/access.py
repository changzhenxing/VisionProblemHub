"""Server-side action and data-scope checks shared by every API surface."""
from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (Department, Issue, IssueCollaborator, Project, ProjectMember,
                     Role, Team, User, UserRole)


def grants(db: Session, user: User, permission: str | None = None) -> list[UserRole]:
    result = []
    for assignment, role in db.execute(select(UserRole, Role).join(Role, UserRole.role_id == Role.id)
                                       .where(UserRole.user_id == user.id)).all():
        try:
            allowed = set(json.loads(role.permissions_json))
        except (ValueError, TypeError):
            allowed = set()
        if permission is None or permission in allowed:
            result.append(assignment)
    return result


def _project_members(db: Session, project_id: int) -> set[int]:
    return set(db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)).all())


def _scope_matches_project(db: Session, user: User, assignment: UserRole, project: Project,
                           *, action: bool = False) -> bool:
    scope = assignment.scope
    if scope == "all":
        return True
    members = _project_members(db, project.id)
    if scope == "self":
        return project.manager_id == user.id if action else user.id in members or project.manager_id == user.id
    if scope == "project":
        return project.id == assignment.scope_id if assignment.scope_id else user.id in members
    if scope in {"team", "department"}:
        if scope == "team":
            team_id = assignment.scope_id or user.team_id
            return bool(team_id and db.scalar(select(User.id).where(User.id.in_(members), User.team_id == team_id).limit(1)))
        team = db.get(Team, user.team_id) if user.team_id else None
        department_id = assignment.scope_id or (team.department_id if team else None)
        return bool(department_id and db.scalar(select(User.id).join(Team, User.team_id == Team.id)
                                                .where(User.id.in_(members), Team.department_id == department_id).limit(1)))
    return False


def can_project(db: Session, user: User, project: Project, permission: str | None = None) -> bool:
    action = permission not in {None, "issues.write", "feedback.write"}
    return bool(user.active and any(_scope_matches_project(db, user, grant, project, action=action)
                                    for grant in grants(db, user, permission)))


def can_issue(db: Session, user: User, issue: Issue, permission: str | None = None) -> bool:
    if not user.active:
        return False
    for grant in grants(db, user, permission):
        if grant.scope == "self":
            involved = issue.owner_id == user.id or issue.created_by_id == user.id or db.get(IssueCollaborator, (issue.id, user.id)) is not None
            if involved:
                return True
            if issue.project.manager_id == user.id:
                return True
        elif _scope_matches_project(db, user, grant, issue.project, action=permission is not None):
            return True
    return False


def can_person(db: Session, user: User, subject: User, *, sensitive: bool = False,
               manage: bool = False) -> bool:
    if user.id == subject.id and not manage:
        return True
    permission = "people.manage" if manage or sensitive else "people.read"
    for grant in grants(db, user, permission):
        if grant.scope == "all":
            return True
        if grant.scope == "self":
            continue
        if grant.scope == "team" and subject.team_id and subject.team_id == (grant.scope_id or user.team_id):
            return True
        if grant.scope == "department" and subject.team_id:
            subject_team = db.get(Team, subject.team_id)
            actor_team = db.get(Team, user.team_id) if user.team_id else None
            if subject_team and subject_team.department_id == (grant.scope_id or (actor_team.department_id if actor_team else None)):
                return True
        if grant.scope == "project" and not sensitive:
            project_ids = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == subject.id)).all())
            if grant.scope_id in project_ids or (grant.scope_id is None and db.scalar(
                    select(ProjectMember.project_id).where(ProjectMember.user_id == user.id,
                                                           ProjectMember.project_id.in_(project_ids)).limit(1))):
                return True
    return False


def require_project(db: Session, user: User, project: Project | None, permission: str | None = None) -> Project:
    if not project or not can_project(db, user, project, permission):
        raise HTTPException(404 if permission is None else 403, "项目不可访问")
    return project


def require_issue(db: Session, user: User, issue: Issue | None, permission: str | None = None) -> Issue:
    if not issue or not can_issue(db, user, issue, permission):
        raise HTTPException(404 if permission is None else 403, "问题不可访问")
    return issue
