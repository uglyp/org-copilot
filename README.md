# 知识库 Copilot（KB-Copilot）

本仓库包含 **FastAPI 后端**与 **Vue 3 前端**。

**本地开发（虚拟环境、依赖、启动 uvicorn、MySQL 迁移、Ollama 与本地模型）** 的完整说明见：**[`docs/LOCAL_DEV_AND_OLLAMA.md`](docs/LOCAL_DEV_AND_OLLAMA.md)**（若你通过 Git 克隆后没有 `docs/` 目录，说明该文档未纳入版本库，请使用本地备份或团队 Wiki 中的同名字稿）。下文为快速步骤；与长文档重复处以该文件为准。

**后端架构、依赖分工、RAG 数据流与目录地图**：[`backend/docs/BACKEND_TUTORIAL.md`](backend/docs/BACKEND_TUTORIAL.md)（同上，若目录缺失请从备份获取；与上一文档互为补充：教程偏「理解与跟代码」，长手册偏「命令与排错」）。

## 后端（`backend/`）

1. 创建虚拟环境并安装依赖：

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. 在 **`backend/.env`**（与 `app/` 同级）中配置环境变量（已固定从该路径读取，与你在哪个目录执行 `uvicorn` 无关）：

   - `DATABASE_URL`：异步驱动为 `mysql+aiomysql://...`；密码中的 `!` 等字符需 **URL 编码**（例如 `!` → `%21`）。若出现 MySQL `1045 Access denied`，说明库地址或密码与 `DATABASE_URL` 不一致。
   - `FERNET_KEY`：运行 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成。
   - `JWT_SECRET`：随机长字符串。

3. MySQL 建库（示例）：

   ```sql
   CREATE DATABASE IF NOT EXISTS kb_copilot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

4. 迁移：

   ```bash
   export PYTHONPATH=.
   alembic upgrade head
   ```

   若你拉取代码后出现新的迁移（如忘记密码相关表），请再次执行 `alembic upgrade head`。

5. 启动（在 `backend` 目录、已激活 `.venv`）：

   ```bash
   source .venv/bin/activate
   export PYTHONPATH=.
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   健康检查：<http://127.0.0.1:8000/health>  
   API 前缀：`/api/v1`（例如 `/api/v1/auth/login`）。

### 忘记密码

- 前端：`/forgot-password`、`/reset-password`（登录页可点「忘记密码」）。
- 数据库表 `password_reset_tokens` 仅存 **token 的 SHA256**，不存明文密码。
- **无邮件服务**时：在 `backend/.env` 将 `PASSWORD_RESET_TOKEN_IN_RESPONSE=true`（仅开发），申请重置后接口会返回 `reset_url`，便于本地联调；**生产环境务必为 `false`**，并后续接入邮件或短信发送重置链接。

## 前端（`frontend/`）

1. 安装与开发：

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

2. 开发环境通过 Vite 将 `/api` 代理到 `http://127.0.0.1:8000`，`src/api/http.ts` 默认 `baseURL` 为 `/api/v1`，与后端前缀一致。

3. 若部署到静态服务器且无法配置代理，构建前设置 `VITE_API_BASE`（例如 `http://你的后端:8000/api/v1`）。

4. **对话界面**使用 **[vue-element-plus-x](https://element-plus-x.com)**：`Conversations`（会话列表）、`Sender`（输入区）、`XMarkdown` / `Typewriter`（回答渲染）、`ThoughtChain`（检索阶段进度），对接本项目 SSE（`src/api/sse.ts`）；知识库与模型页与全局主题样式（`src/styles/kb-theme.css`）保持一致。

## 向量与知识库（RAG）

- **推荐（默认）**：在 `backend/.env` 中设置 `USE_LOCAL_EMBEDDING=true`，使用 **fastembed** 本地向量（`LOCAL_EMBEDDING_MODEL`，默认 `BAAI/bge-small-zh-v1.5`）。**无需** OpenAI embedding Key；首次运行会从 HuggingFace 拉取 ONNX 模型（需可访问外网或配置镜像）。
- **远程 API**：设 `USE_LOCAL_EMBEDDING=false`，并在「模型设置」中配置 OpenAI 兼容 **embedding**，或在 `.env` 中设置 `EMBEDDING_API_KEY` / `EMBEDDING_API_BASE` / `EMBEDDING_MODEL`，系统会尝试自动创建「Embedding（API）」提供商。
- **对话模型**：DeepSeek 仅用于 **chat**。在 `.env` 中配置 `DEEPSEEK_API_KEY` 后，尚无提供商的用户会自动创建 DeepSeek 对话模型。

### Ollama 本地对话（Qwen 3B 等）

**分步说明、环境变量表、`curl` 校验、与 `httpx` / RAG 的关系** 见 **[`docs/LOCAL_DEV_AND_OLLAMA.md`](docs/LOCAL_DEV_AND_OLLAMA.md)**。本节为最小操作摘要。

适合本机已装 [Ollama](https://ollama.com)，想用 **OpenAI 兼容接口** 接本地 Qwen 做 **chat**；**向量**仍建议用 `.env` 里 `USE_LOCAL_EMBEDDING=true`（BGE / fastembed），不必改用 Ollama embedding。

1. **安装并拉模型**（示例为 Qwen2.5 3B；具体名称以 `ollama.com/library` 为准）：

   ```bash
   ollama pull qwen2.5:3b
   ollama list   # 确认模型名，例如 qwen2.5:3b
   ```

2. **本应用「模型设置」里新建提供商**（与 DeepSeek **并存**时）：

   - **API Base**：`http://127.0.0.1:11434`（**不要**带 `/v1`，后端会自行拼接 `/v1/chat/completions`）
   - **API Key**：任意非空占位即可（如 `ollama`）；Ollama 不校验，但本系统创建提供商时要求填写
   - **模型**：新增一条 **chat** 模型，`model_id` 填 Ollama 里的名字（如 `qwen2.5:3b`）。**若默认仍用 DeepSeek**，只把 DeepSeek 那条 chat 设为默认，Ollama 不要勾选默认。

3. **一键注入（推荐）**：在 `backend/.env` 中设置 `OLLAMA_BASE=http://127.0.0.1:11434` 与 `OLLAMA_CHAT_MODEL=qwen2.5:3b`，重启后端后 **重新登录** 或打开对话页；系统会自动创建「Ollama」提供商（非默认），下拉框即可选本地模型。若已手动配置过同名或同地址的提供商，不会重复创建。

4. **对话页切换**：输入区上方的 **「对话模型」** 可选「默认（DeepSeek）」或本地 Ollama；选择保存在浏览器本地，刷新后仍保留。

5. **验证**：浏览器能访问 <http://127.0.0.1:11434> 即服务已起；选中 Ollama 后发消息走本地 Qwen。

若拉取失败，可执行 `ollama search qwen` 或在官网库页查看当前可用的 3B 级标签。

### Docker 版 Qdrant（可选）

默认使用 **嵌入式** 存储（`QDRANT_PATH=./data/qdrant_local`，无需单独进程）。若希望用 **Web 控制台**、多 worker 或团队共用同一向量库，可改用官方镜像：

1. **启动容器**（数据持久化到本机目录 `./qdrant_storage`）：

   ```bash
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
     -v "$(pwd)/qdrant_storage:/qdrant/storage" \
     qdrant/qdrant:latest
   ```

2. **Web UI**：浏览器打开 <http://127.0.0.1:6333/dashboard> 可查看 collections、点、payload。

3. **本应用配置**：在 `backend/.env` 中设置（**不要**再同时依赖嵌入式路径存数据）：

   ```env
   QDRANT_URL=http://127.0.0.1:6333
   ```

   可选注释掉或保留 `QDRANT_PATH`（未设置 `QDRANT_URL` 时仍使用嵌入式）。

4. **切换说明**：嵌入式与 Docker 里的数据**不是**同一套；切换后需重新上传文档，或自行迁移/导出导入。  
5. **查看向量**：`export PYTHONPATH=. && python scripts/inspect_qdrant.py`（Docker 模式下可与 uvicorn 同时运行）。

若曾用其他向量维度写入过 Qdrant，更换模型维度后请**清空**嵌入式目录或删除 Docker 中的同名 collection，或修改 `QDRANT_COLLECTION` 名称，否则入库可能失败。

## 功能入口

- **对话**：默认 chat 就绪即可（DeepSeek 自动注入或手动配置）。
- **知识库上传与基于知识库问答**：需 **向量就绪**（本地 fastembed 或远程 embedding）。
