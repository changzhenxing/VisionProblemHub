# 以问题驱动的工业视觉项目管理与知识沉淀平台 V2.0

## 产品定位

团队成员只需要正常完成工作：**记录问题、反馈进展、更新解决办法、上传图片/视频/文件、验证并关闭问题**。
系统在后台自动完成：

- 项目状态与延期管理
- 问题全过程留痕
- 问题复盘草稿
- 项目复盘草稿
- 工业视觉案例卡沉淀
- Agent/RAG 可用的结构化知识输出

核心原则：**项目管理、复盘、知识沉淀都应成为日常解决问题的副产品，而不是额外工作。**

## 技术栈

- FastAPI
- SQLAlchemy
- SQLite + WAL
- Vue 3 + Vite（前端源码在 `frontend/`，构建产物在 `app/static/`）
- 本地文件系统保存图片、视频和附件

面向 10 人左右局域网团队的第一阶段原型。当前尚无身份认证和角色权限控制，正式团队部署前需补齐。数据库访问层已隔离，未来可迁移 PostgreSQL。

## Windows 快速启动

1. 安装 Python 3.11+
2. 双击 `setup_and_start.bat`
3. 浏览器打开 `http://127.0.0.1:8765/`（不要打开 `0.0.0.0`）
4. 局域网成员访问 `http://服务器IP:8765/`

首次启动会自动创建默认用户 `管理员`，进入系统后可添加团队成员和项目。

仓库已包含构建好的前端页面，普通部署仍只需 Python。修改前端时需要 Node.js 22.18+ 或 24.12+：

```bash
cd frontend
npm ci
npm run build
```

开发时可运行 `npm run dev`，Vite 会将 `/api` 和 `/uploads` 代理到本机 8765 端口的 FastAPI。构建会更新 `app/static/`，提交前端改动时需同时提交构建产物。可设置 `VISION_PORT` 环境变量自定义后端端口，启动脚本和 Vite 代理都会使用它。

## 日常使用

普通成员主要只做四件事：

1. **新增问题**：项目、类型、描述、优先级、Owner、计划关闭时间；图片/视频可直接上传。
2. **随手反馈**：像聊天一样补充进展，可带图片、视频、日志、Excel 等。
3. **更新解决办法 / 验证结果**：每次尝试都会作为事件保留，失败方案不会被最终方案覆盖。
4. **关闭问题**：系统自动记录实际关闭时间、延期情况并更新复盘与知识案例。

## 备份

运行：

```bash
python scripts/backup.py
```

会使用 SQLite 在线备份机制生成到 `data/backups/`。

## 测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 关键目录

- `app/` 后端与前端构建产物
- `frontend/` Vue 源码与 Vite 配置
- `data/vision_knowledge.db` 数据库
- `data/uploads/` 图片、视频、文件
- `data/backups/` 备份
- `tests/` 自动化测试
- `DESIGN.md` 详细设计
- `ACCEPTANCE.md` 用户验收清单
- `VALIDATION.md` 当前版本验证结果
