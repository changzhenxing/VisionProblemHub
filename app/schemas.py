from datetime import date
from typing import Optional
from pydantic import BaseModel, Field

STAGES = ["需求确认", "方案设计", "开发验证", "现场验证", "验收关闭"]
ISSUE_TYPES = ["成像", "算法", "软件", "交付"]
PRIORITIES = ["紧急重要", "重要不紧急", "紧急不重要", "一般"]
ISSUE_STATUSES = ["待处理", "处理中", "有风险", "阻塞", "已关闭"]
EVENT_TYPES = ["进展反馈", "解决办法", "验证结果", "根因判断"]
EVENT_OUTCOMES = ["待验证", "失败", "部分有效", "成功"]
ATTACHMENT_ROLES = ["问题证据", "方案说明", "验证证据", "最终结果", "其他"]
KNOWLEDGE_STATES = ["自动提取", "人工确认", "多项目验证", "已废弃"]

class ProjectCreate(BaseModel):
    name: str
    manager_id: int
    current_stage: str = "需求确认"
    planned_completion_date: date
    description: Optional[str] = None

class ProjectPatch(BaseModel):
    actor_id: Optional[int] = None
    name: Optional[str] = None
    manager_id: Optional[int] = None
    current_stage: Optional[str] = None
    planned_completion_date: Optional[date] = None
    description: Optional[str] = None

class IssueCreate(BaseModel):
    project_id: int
    issue_type: str
    description: str = Field(min_length=1)
    priority: str = "重要不紧急"
    status: str = "待处理"
    owner_id: int
    planned_close_date: date
    close_standard: Optional[str] = None
    created_by_id: int

class IssuePatch(BaseModel):
    actor_id: int
    issue_type: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    owner_id: Optional[int] = None
    planned_close_date: Optional[date] = None
    close_standard: Optional[str] = None
    delay_reason: Optional[str] = None

class ManualRetrospectivePatch(BaseModel):
    actor_id: int
    values: dict[str, str | None]
    confirm: bool = False

class KnowledgePatch(BaseModel):
    actor_id: int
    values: dict[str, str | int | None]
