# V2.0 验证报告

验证日期：2026-09-28

## 自动化测试

`pytest -q`

结果：**8 / 8 通过**。

覆盖：

1. 问题创建 → 图片证据 → 进展 → 失败方案 → 成功方案 → 视频验证 → 关闭 → 自动问题复盘 → 自动知识案例。
2. 人工修改问题复盘后字段锁定，后续自动提取不覆盖；人工修订事件留痕；知识可信度提升为“人工确认”。
3. 同值保存不产生历史噪声；优先级和计划时间真实变化会记录事件。
4. 项目复盘、统计趋势、知识库和 Agent 导出接口正常。
5. SQLite WAL 下模拟 30 个问题并发新增，30 / 30 成功。
6. SQLite `journal_mode=wal`。
7. 项目阶段/计划时间变化自动留痕；问题首次反馈自动从“待处理”推进到“处理中”。
8. 图片/视频附件可通过静态文件接口访问；知识人工修订锁定后自动再生成不会覆盖。

## 数据库检查

- `journal_mode = wal`
- `foreign_keys = 1`
- 核心表：
  - users
  - projects
  - project_events
  - issues
  - issue_events
  - attachments
  - issue_retrospectives
  - project_retrospectives
  - knowledge_cases

## 静态与启动检查

- Python `compileall`：通过
- JavaScript `node --check`：通过
- FastAPI/Uvicorn 真实启动：通过
- `/`：HTTP 200
- `/api/users`：HTTP 200
- SQLite 在线备份脚本：通过

## Windows 本机补充验证（2026-09-28）

- Python 3.12 环境中完整测试集：8 / 8 通过；Python `compileall` 与 JavaScript `node --check` 通过。
- 独立数据目录启动 Uvicorn；首页、静态资源及主要 API 实际 HTTP 访问返回 200。
- 浏览器中实际完成“新建项目 → 新增问题 → 提交进展”，确认首次反馈后状态自动变为“处理中”，问题复盘和知识案例页面可查看。
- 在线备份生成后，SQLite `PRAGMA integrity_check` 返回 `ok`，备份中包含浏览器创建的问题。

当前测试用例存在顺序依赖：完整测试集通过，但单独运行 `test_manual_retro_is_preserved_and_correction_logged` 会因缺少前置测试数据而失败。需改为独立测试夹具。

当前接口没有身份认证和角色权限控制，文件上传会一次性读入内存；正式团队部署前需处理。规则式根因提取也需要人工确认，浏览器示例中的“定位为”未被自动识别。
