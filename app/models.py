from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, Text, Date, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(40), default="团队成员")
    role_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roles.id"), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    assigned_role: Mapped[Optional[Role]] = relationship(foreign_keys=[role_id])

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    permissions_json: Mapped[str] = mapped_column(Text, default="[]")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))

class UserRole(Base):
    __tablename__ = "user_roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    scope: Mapped[str] = mapped_column(String(20), default="self")
    scope_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    member_role: Mapped[str] = mapped_column(String(30), default="成员")

class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    due_date: Mapped[date] = mapped_column(Date)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class IssueCollaborator(Base):
    __tablename__ = "issue_collaborators"
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)

class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("issue_events.id"), nullable=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(30), default="project")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

class FeedbackAttachment(Base):
    __tablename__ = "feedback_attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("feedback.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)

class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    fact: Mapped[str] = mapped_column(Text, default="")
    judgment: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(Text, default="")
    commitment: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    visibility: Mapped[str] = mapped_column(String(30), default="project")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class OneOnOne(Base):
    __tablename__ = "one_on_ones"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    actions: Mapped[str] = mapped_column(Text, default="")
    resource_request: Mapped[str] = mapped_column(Text, default="")
    growth_goal: Mapped[str] = mapped_column(Text, default="")
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class SkillEvidence(Base):
    __tablename__ = "skill_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("issue_events.id"), nullable=True)
    skill: Mapped[str] = mapped_column(String(80))
    evidence: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="待确认")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class GrowthAction(Base):
    __tablename__ = "growth_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    one_on_one_id: Mapped[Optional[int]] = mapped_column(ForeignKey("one_on_ones.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="进行中")

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(String(400))
    issue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("issues.id"), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class WeeklyReport(Base):
    __tablename__ = "weekly_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date)
    content: Mapped[str] = mapped_column(Text)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    current_stage: Mapped[str] = mapped_column(String(30), default="需求确认", index=True)
    planned_completion_date: Mapped[date] = mapped_column(Date, index=True)
    actual_completion_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    manager: Mapped[User] = relationship(foreign_keys=[manager_id])
    issues: Mapped[list[Issue]] = relationship(back_populates="project", cascade="all, delete-orphan")
    events: Mapped[list[ProjectEvent]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="ProjectEvent.created_at")

class ProjectEvent(Base):
    __tablename__ = "project_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    project: Mapped[Project] = relationship(back_populates="events")
    actor: Mapped[Optional[User]] = relationship(foreign_keys=[actor_id])

class Issue(Base):
    __tablename__ = "issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    issue_type: Mapped[str] = mapped_column(String(30), index=True)
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="待处理", index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    planned_close_date: Mapped[date] = mapped_column(Date, index=True)
    actual_close_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    close_standard: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delay_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    project: Mapped[Project] = relationship(back_populates="issues")
    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    creator: Mapped[User] = relationship(foreign_keys=[created_by_id])
    events: Mapped[list[IssueEvent]] = relationship(back_populates="issue", cascade="all, delete-orphan", order_by="IssueEvent.created_at")

class IssueEvent(Base):
    __tablename__ = "issue_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    issue: Mapped[Issue] = relationship(back_populates="events")
    actor: Mapped[Optional[User]] = relationship(foreign_keys=[actor_id])
    attachments: Mapped[list[Attachment]] = relationship(back_populates="event", cascade="all, delete-orphan")

class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("issue_events.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    media_kind: Mapped[str] = mapped_column(String(20), default="file", index=True)
    role: Mapped[str] = mapped_column(String(30), default="其他", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    relative_path: Mapped[str] = mapped_column(String(500))
    uploaded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    event: Mapped[IssueEvent] = relationship(back_populates="attachments")
    uploaded_by: Mapped[Optional[User]] = relationship(foreign_keys=[uploaded_by_id])

class IssueRetrospective(Base):
    __tablename__ = "issue_retrospectives"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), unique=True, index=True)
    phenomenon: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    process_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_solution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validation_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prevention: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    locked_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    confirmed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    auto_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

class ProjectRetrospective(Base):
    __tablename__ = "project_retrospectives"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_problems: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delay_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    improvements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    knowledge_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    locked_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    confirmed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    auto_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

class KnowledgeCase(Base):
    __tablename__ = "knowledge_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    scene: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    problem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_solution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prevention: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applicability: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_state: Mapped[str] = mapped_column(String(30), default="自动提取", index=True)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
