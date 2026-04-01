# 变更记录

本文件遵循用户可见的**语义化摘要**：重要功能、修复与破坏性变更。版本号与 [backend/pyproject.toml](backend/pyproject.toml)、前端 `package.json` 对齐时可在此同步更新。

**自动维护：** 推送 `main` 后可用 Release Please 根据约定式提交打开「发布 PR」并更新本文件与后端版本，见 [docs/CHANGELOG_AUTOMATION.md](docs/CHANGELOG_AUTOMATION.md)。

## 未发布

### 新增

- **后端**：`PATCH /api/v1/auth/me` 更新当前用户分行/角色/密级/部门/组织 ID，响应内返回**新 JWT**。
- **前端**：「账户与权限」页（`/settings/account`）；注册页可选填企业权限；知识库支持组织共享、上传时文档权限折叠表单与列表展示分行/密级/部门。

### 变更

- **企业 ACL**：`ENTERPRISE_ACL_ENABLED` 默认改为 **true**；RAG 拼上下文前**始终**按文档元数据做权限过滤（与知识库列表/下载一致）。仅当需兼容无 `branch`/`security_level` 字段的旧 Milvus 集合时，再在 `.env` 中设 `ENTERPRISE_ACL_ENABLED=false` 并处理向量数据迁移。
- **文档**：[术语表与概念说明](docs/术语表与概念说明.md) 补充企业权限相关表字段说明。

## [0.4.0](https://github.com/uglyp/KB-Copilot/compare/v0.3.0...v0.4.0) (2026-03-31)


### 新增

* add dual database support for MySQL and PostgreSQL ([5122587](https://github.com/uglyp/KB-Copilot/commit/5122587d642a576992c43faee0c3dda391b05cbf))

## [0.3.0](https://github.com/uglyp/KB-Copilot/compare/v0.2.0...v0.3.0) (2026-03-31)


### 新增

* enhance MySQL connection handling in the backend ([c90c53b](https://github.com/uglyp/KB-Copilot/commit/c90c53b9d722a8cf427d3c39834f5ee3403f2e38))

## [0.2.0] - 2026-03-31

### 破坏性变更

- 向量存储由 **Qdrant** 切换为 **Milvus**：默认使用 **Milvus Lite**（本地 SQLite 文件，由 `pymilvus[milvus-lite]` 提供）；也可通过 `MILVUS_URI` 连接独立 Milvus 服务。
- 环境变量需从 Qdrant 相关项改为 **`MILVUS_URI`**（可选）、**`MILVUS_DB_PATH`**、**`MILVUS_TOKEN`**、**`MILVUS_COLLECTION`** 等，详见 `backend/.env.example` 与 README。
- 关系型库中 `chunks` 表字段由 `qdrant_point_id` 重命名为 **`milvus_point_id`**；升级需执行 `alembic upgrade head`。
- **向量数据与 Qdrant 不兼容**，升级后需对知识库文档**重新入库**以写入 Milvus。

### 变更

- 移除 `qdrant-client` 与 `qdrant_store`；新增 `milvus_store` 封装检索、写入与按文档删除。
- RAG 与入库流程改为调用 Milvus；本地调试脚本由 `inspect_qdrant` 替换为 **`inspect_milvus`**。
- `.gitignore` 补充 Milvus Lite 数据路径及在 `backend/` 目录下偶发的临时 `tmpr*.db` 文件。

## [0.1.0] - 2026-03-30

### 新增

- 根目录开源基建：MIT 许可证、[CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md)、[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- GitHub Actions CI：后端 `uv sync` 与导入校验，前端 `npm install` 与生产构建。
- Issue 模板：缺陷报告与功能建议。
- README 面向发现与协作的摘要、架构示意、Roadmap、目录与截图占位说明。
- [docs/GITHUB_REPOSITORY_METADATA.md](docs/GITHUB_REPOSITORY_METADATA.md)：仓库 Description 与 Topics 的推荐文案（需在 GitHub About 中手动填写）。
