# KB-Copilot 后端

FastAPI 应用；依赖由 **`pyproject.toml`** 声明，**`uv.lock`** 锁定版本（**uv** 以此为准）。**`requirements.txt`** 为与 `pyproject.toml` **同步的简版列表**，供 **`pip install -r`** 使用（无哈希、无传递依赖展开，便于阅读与非 uv 环境）。

## 依赖与虚拟环境（推荐：uv）

1. 安装 [uv](https://docs.astral.sh/uv/)（任选其一）：

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   # 或: brew install uv
   ```

2. 在 `backend/` 下同步环境（会创建 `.venv` 并以可编辑模式安装本包，无需再设 `PYTHONPATH`）：

   ```bash
   cd backend
   uv sync
   ```

   **国内 PyPI 镜像**（可选，拉取 `paddlepaddle` 等较大包时更稳）：

   ```bash
   uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple
   uv sync --extra image --default-index https://pypi.tuna.tsinghua.edu.cn/simple
   ```

   若清华源缺少 Paddle 官方 wheel，可改用 `https://mirror.baidu.com/pypi/simple`，或按 [Paddle 安装页](https://www.paddlepaddle.org.cn/install/quick) 选择平台。环境变量也可用 `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`。

3. 仅使用 pip 时（不推荐作日常开发主路径）：

   ```bash
   pip install -r requirements.txt
   ```

## 环境变量

复制 `backend/.env.example` 为 **`backend/.env`**（与 `app/` 同级）。说明见仓库根目录 `README.md` 后端章节。

## 企业权限（MySQL / PostgreSQL 通用）

- 迁移 `alembic upgrade head` 后为 `users` / `documents` / `knowledge_bases` 增加分行、密级、部门、组织共享等字段；**行级控制由应用层 SQLAlchemy 条件实现**，与 PostgreSQL RLS 等价目标一致，但不依赖 RLS。
- **默认 `ENTERPRISE_ACL_ENABLED=true`**（可在 `.env` 设为 `false`）：Milvus 检索在 `filter` 中叠加 `branch` / `security_level`；对话 RAG 在拼上下文前仍会做**文档级**校验（与列表/下载一致）。若本地已有**无 ACL 字段**的旧 Milvus 集合，请删除 `MILVUS_DB_PATH` 文件或换新 **`MILVUS_COLLECTION`** 后 **重新入库**。
- 一键清 Lite 库并重跑 `ready` 文档流水线：`uv run python scripts/milvus_acl_upgrade.py --yes`（独立 Milvus 见脚本内 `--drop-collection` 说明）。
- 知识库可选 **`is_org_shared` + `org_id`**：同 `org_id` 的用户可访问属主设为共享的知识库；文档列表/下载/RAG 仍受文档级 ACL 约束。
- 本地单测：`uv run python -m unittest discover -s tests -p 'test_*.py' -v`

## 关系型数据库（MySQL / PostgreSQL 二选一）

- 应用：`DATABASE_URL` 使用异步驱动 **`mysql+aiomysql://`** 或 **`postgresql+asyncpg://`**；可选 **`RELATIONAL_DB=mysql`** / **`postgresql`** 与 URL 一致时做校验。
- Alembic：会自动映射为 **`mysql+pymysql`** / **`postgresql+psycopg`**，无需单独配置。
- 从 MySQL 迁到 PostgreSQL：目标库先 `alembic upgrade head`，再用同步 URL 运行  
  `scripts/sync_relational_data.py`（见脚本内说明与 `backend/.env.example` 注释）。

## 数据库迁移（Alembic）

在 `backend/` 目录执行：

```bash
uv run alembic upgrade head
```

新建迁移（示例）：`uv run alembic revision --autogenerate -m "描述"`，再检查 `alembic/versions/` 后提交；**若变更含方言差异**，请在两种库上各跑一遍 `upgrade head`（本地或 CI）后再合并。

## 启动（Uvicorn）

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：<http://127.0.0.1:8000/health>。

## 维护依赖（开发者）

1. 编辑 **`pyproject.toml`** 中 `[project].dependencies`。
2. **`requirements.txt`** 中同名依赖行保持与上一步一致（供 pip 用户；勿用 `uv export` 覆盖本文件，否则会生成带哈希的巨型清单，且含 `-e .`，与「纯 pip 装第三方库 + PYTHONPATH」的常见用法不一致）。
3. `uv lock` 更新 **`uv.lock`**，`uv sync` 同步本地 `.venv`。
4. 提交 **`pyproject.toml`、`uv.lock`、`requirements.txt`**。

若 CI 需要「pip 可用的完整锁定文件」，可另存为其它文件名，例如：  
`uv export --frozen --no-dev -o requirements-locked.txt`（不要覆盖上面的简版 `requirements.txt`）。
