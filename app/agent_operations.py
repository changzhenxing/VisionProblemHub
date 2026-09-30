"""Explicit, reviewable business operations exposed to the conversational agent.

The model only supplies arguments. The server selects the route and method.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    fields: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    permission: str | None = None
    mode: str = "json"  # json, form, none, or query


def op(label, method, path, fields="", required="", permission=None, mode="json"):
    return Operation(label, method, path, tuple(fields.split()), tuple(required.split()), permission, mode)


OPERATIONS = {
    "create_project": op("创建项目", "POST", "/api/projects", "name manager_id current_stage planned_completion_date description", "name manager_id planned_completion_date", "projects.write"),
    "update_project": op("修改项目", "PATCH", "/api/projects/{project_id}", "name manager_id current_stage planned_completion_date description", permission="projects.write"),
    "add_project_member": op("配置项目成员", "PUT", "/api/projects/{project_id}/members/{user_id}", "member_role", permission="org.manage"),
    "remove_project_member": op("移除项目成员", "DELETE", "/api/projects/{project_id}/members/{user_id}", permission="org.manage", mode="none"),
    "create_milestone": op("创建里程碑", "POST", "/api/projects/{project_id}/milestones", "title due_date", "title due_date", "milestones.write"),
    "update_milestone": op("修改里程碑", "PATCH", "/api/milestones/{milestone_id}", "title due_date completed", permission="milestones.write"),
    "create_issue": op("创建问题", "POST", "/api/issues", "project_id issue_type description priority status owner_id planned_close_date close_standard", "project_id issue_type description owner_id planned_close_date", "issues.write"),
    "update_issue": op("修改问题", "PATCH", "/api/issues/{issue_id}", "issue_type description priority status owner_id planned_close_date close_standard delay_reason", permission="issues.write"),
    "add_issue_event": op("记录问题进展", "POST", "/api/issues/{issue_id}/events", "event_type content outcome attachment_role upload_ids", "event_type content", "issues.write", "form"),
    "upload_issue_creation_attachments": op("补充问题创建附件", "POST", "/api/issues/{issue_id}/creation-attachments", "attachment_role upload_ids", "upload_ids", "issues.write", "form"),
    "set_issue_collaborators": op("配置问题协同人员", "PUT", "/api/issues/{issue_id}/collaborators", "user_ids", "user_ids", "issues.write"),
    "add_feedback": op("发表管理反馈", "POST", "/api/issues/{issue_id}/feedback", "kind content recipient_id visibility event_id upload_ids", "kind content", "feedback.write", "form"),
    "add_decision": op("记录沟通结论", "POST", "/api/issues/{issue_id}/decisions", "fact judgment decision commitment owner_id due_date visibility", permission="feedback.write"),
    "update_issue_retrospective": op("修订问题复盘", "PATCH", "/api/issues/{issue_id}/retrospective", "values confirm", "values", "issues.write"),
    "regenerate_issue_retrospective": op("重新生成问题复盘", "POST", "/api/issues/{issue_id}/retrospective/regenerate", "force", permission="issues.write", mode="query"),
    "update_project_retrospective": op("修订项目复盘", "PATCH", "/api/projects/{project_id}/retrospective", "values confirm", "values", "projects.write"),
    "regenerate_project_retrospective": op("重新生成项目复盘", "POST", "/api/projects/{project_id}/retrospective/regenerate", "force", permission="projects.write", mode="query"),
    "update_knowledge": op("修订知识案例", "PATCH", "/api/knowledge/{case_id}", "values", "values", "knowledge.write"),
    "regenerate_knowledge": op("重新生成知识案例", "POST", "/api/knowledge/{case_id}/regenerate", "force", permission="knowledge.write", mode="query"),
    "create_department": op("创建部门", "POST", "/api/org/departments", "name", "name", "org.manage"),
    "create_team": op("创建团队", "POST", "/api/org/teams", "name department_id", "name department_id", "org.manage"),
    "confirm_skill": op("审核能力证据", "PATCH", "/api/skills/{evidence_id}", "state", "state"),
    "create_one_on_one": op("记录一对一沟通", "POST", "/api/people/{person_id}/one-on-ones", "summary actions resource_request growth_goal"),
    "confirm_one_on_one": op("确认一对一纪要", "POST", "/api/one-on-ones/{note_id}/confirm", mode="none"),
    "update_growth_action": op("更新成长行动", "PATCH", "/api/growth-actions/{action_id}", "status", "status"),
    "read_notification": op("标记提醒已读", "POST", "/api/notifications/{notification_id}/read", mode="none"),
    "save_weekly_report": op("保存周报", "PUT", "/api/reports/weekly", "week_start content confirm", "week_start content", "reports.write"),
    "create_user": op("创建用户", "POST", "/api/users", "name role_id team_id scope scope_id", "name role_id", "users.manage"),
    "update_user": op("修改用户", "PATCH", "/api/admin/users/{user_id}", "name role_id active team_id", permission="users.manage"),
    "reset_user_password": op("重置用户密码", "PATCH", "/api/admin/users/{user_id}", permission="users.manage"),
    "set_user_roles": op("配置用户角色", "PUT", "/api/admin/users/{user_id}/roles", "assignments", "assignments", "users.manage"),
    "create_role": op("创建角色", "POST", "/api/admin/roles", "name description permissions", "name", "roles.manage"),
    "update_role": op("修改角色", "PATCH", "/api/admin/roles/{role_id}", "name description permissions", "name", "roles.manage"),
    "delete_role": op("删除角色", "DELETE", "/api/admin/roles/{role_id}", permission="roles.manage", mode="none"),
    "create_model": op("新增模型配置", "POST", "/api/agent/models", "name base_url model_name is_active", "name base_url model_name", "models.manage"),
    "update_model": op("修改模型配置", "PUT", "/api/agent/models/{model_id}", "name base_url model_name is_active clear_api_key", "name base_url model_name", "models.manage"),
    "activate_model": op("启用模型配置", "PUT", "/api/agent/models/{model_id}", permission="models.manage"),
    "delete_model": op("删除模型配置", "DELETE", "/api/agent/models/{model_id}", permission="models.manage", mode="none"),
    "test_model": op("测试模型连接", "POST", "/api/agent/models/{model_id}/test", permission="models.manage", mode="none"),
    "change_my_password": op("修改我的密码", "POST", "/api/auth/password"),
}

# Every read route here passes through the same auth middleware and endpoint checks.
READ_PATHS = (
    "/api/config", "/api/users", "/api/admin/users", "/api/admin/roles", "/api/admin/permissions",
    "/api/agent/status", "/api/agent/models",
    "/api/projects", "/api/issues", "/api/knowledge", "/api/knowledge/export/agent",
    "/api/people", "/api/management/overview", "/api/workbench",
    "/api/notifications", "/api/reports/weekly", "/api/audit", "/api/stats",
    "/api/org/departments", "/api/org/teams",
    "/api/projects/{project_id}", "/api/projects/{project_id}/members",
    "/api/projects/{project_id}/milestones", "/api/projects/{project_id}/retrospective",
    "/api/issues/{issue_id}", "/api/issues/{issue_id}/collaborators",
    "/api/issues/{issue_id}/feedback", "/api/issues/{issue_id}/decisions",
    "/api/issues/{issue_id}/retrospective", "/api/issues/{issue_id}/similar",
    "/api/knowledge/{case_id}", "/api/people/{person_id}", "/api/people/{person_id}/skills",
    "/api/people/{person_id}/one-on-ones", "/api/people/{person_id}/growth-actions",
)
