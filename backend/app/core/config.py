"""
集中管理环境变量与默认值。

- `pydantic-settings`：把 `.env` / 系统环境变量映射成类型安全的 Python 对象；字段名大写对应环境变量（如 `DATABASE_URL`）。
- `@lru_cache` 的 `get_settings()`：进程内只解析一次配置，避免每次请求都读磁盘。
- `Path(__file__).resolve()`：定位「本文件」再向上找 `backend/.env`，不依赖你从哪个目录执行 `uvicorn`。
"""

import inspect
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _filter_pymysql_connect_args(args: dict[str, object]) -> dict[str, object]:
    """只保留当前已安装 pymysql 的 Connection 仍接受的参数。

    PyMySQL 1.4+ 已移除 ``allow_public_key_retrieval``（改由握手流程处理公钥）；
    若仍传入会触发 ``Connection.__init__() got an unexpected keyword argument``。
    """
    if not args:
        return {}
    try:
        import pymysql.connections as pymysql_connections

        accepted = inspect.signature(pymysql_connections.Connection.__init__).parameters
    except (ImportError, TypeError, ValueError):
        return args
    return {k: v for k, v in args.items() if k in accepted}


def mysql_url_and_connect_args(database_url: str) -> tuple[str, dict[str, object]]:
    """处理 MySQL URL 查询串：去掉易引发 SQLAlchemy/pymysql 兼容性问题的参数。

    - 将 ``allow_public_key_retrieval`` 从 URL 中剥离（避免被误传给 SQLAlchemy Connection）。
    - 若当前 pymysql 仍支持该参数，则放入 ``connect_args``；否则丢弃（PyMySQL 1.4+ 通常无需）。
    """
    if not (
        database_url.startswith("mysql+aiomysql://")
        or database_url.startswith("mysql+pymysql://")
    ):
        return database_url, {}
    parsed = urlparse(database_url)
    qsl = parse_qsl(parsed.query, keep_blank_values=True)
    raw_connect: dict[str, object] = {}
    kept: list[tuple[str, str]] = []
    for k, v in qsl:
        if k == "allow_public_key_retrieval":
            raw_connect[k] = str(v).lower() in ("true", "1", "yes", "on")
        else:
            kept.append((k, v))
    new_query = urlencode(kept)
    clean = urlunparse(parsed._replace(query=new_query))
    connect_args = _filter_pymysql_connect_args(raw_connect)
    return clean, connect_args


# 无论从哪里启动 uvicorn，都读取 backend/.env（避免 cwd 不是 backend 时用错默认数据库密码）
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """一项配置 = 类属性；生产环境请用环境变量覆盖默认值，勿把密钥写进代码仓库。"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "OrgCopilot"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = (
        "mysql+aiomysql://root:password@localhost:3306/org_copilot"
    )
    # 可选：mysql | postgresql，与 DATABASE_URL 前缀一致；不设则仅按 URL 推断
    relational_db: Literal["mysql", "postgresql"] | None = None

    jwt_secret: str = "change-me-in-production-use-openssl-rand"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    # Fernet key: generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
    fernet_key: str = ""

    # 二选一：不设 MILVUS_URI 时用 Milvus Lite 本地文件（MILVUS_DB_PATH）；设了则连独立 Milvus（HTTP/gRPC URI）
    milvus_uri: str | None = None
    milvus_db_path: str = "./data/milvus_local.db"
    milvus_collection: str = "kb_chunks"
    # 可选：Zilliz Cloud 或开启鉴权的 Milvus，如 user:password 或 API Key
    milvus_token: str = ""
    embedding_dimensions: int = 1536
    # 对话 RAG：向量召回条数（略大有利于「技术栈/语言」等分散在表格中的描述）
    rag_top_k: int = 12

    # 企业 ACL：默认开启。为 true 时 Milvus 集合须含 branch/security_level 标量；旧向量库无此字段时需换新 MILVUS_COLLECTION 或清空后重入库。可设 false 退回仅 kb_id 过滤（不推荐生产）。
    enterprise_acl_enabled: bool = True
    # 与文档权限中「公共」分行标签一致，须与入库文档默认值一致
    public_branch_label: str = "公共"

    upload_dir: str = "./data/uploads"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Dev only: skip model readiness (do not use in prod)
    allow_chat_without_model_setup: bool = False

    # 若设置 DEEPSEEK_API_KEY，注册/登录且用户尚无提供商时自动创建 DeepSeek（仅对话；向量需另配）
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"

    # Ollama（可选）：配置后自动创建「非默认」chat，对话页可切换到本地模型（与 DeepSeek 并存）
    ollama_base: str = ""
    ollama_chat_model: str = ""

    # 本地向量（fastembed，无需远程 embedding API；首次运行会下载模型）
    use_local_embedding: bool = False
    local_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    # Hugging Face 镜像（国内建议）：https://hf-mirror.com ，可显著缓解下载超时
    hf_endpoint: str | None = None
    # huggingface_hub 单次下载/元数据超时（秒），默认过短易 Errno 60
    hf_hub_download_timeout: int = 600
    hf_hub_etag_timeout: int = 120

    # 可选：远程 OpenAI 兼容 embedding（与 use_local_embedding 二选一；为 True 时忽略此项）
    embedding_api_key: str = ""
    embedding_api_base: str = "https://api.openai.com"
    embedding_model: str = "text-embedding-3-small"

    # 忘记密码：令牌有效期（分钟）；生产勿开启「在响应中返回 token」，仅本地调试无邮件时用
    password_reset_token_ttl_minutes: int = 60
    password_reset_token_in_response: bool = False
    # 用于拼前端重置链接（当 password_reset_token_in_response 为 true 时返回 reset_url）
    password_reset_frontend_base: str = "http://localhost:5173"

    @field_validator("database_url")
    @classmethod
    def database_url_must_use_supported_async_driver(cls, v: str) -> str:
        if v.startswith("mysql+aiomysql://") or v.startswith("postgresql+asyncpg://"):
            return v
        raise ValueError(
            "DATABASE_URL 须以 mysql+aiomysql:// 或 postgresql+asyncpg:// 开头（应用异步驱动）"
        )

    @model_validator(mode="after")
    def relational_db_matches_url(self) -> Self:
        if self.relational_db is None:
            return self
        if self.relational_db == "mysql" and not self.database_url.startswith("mysql+"):
            raise ValueError("RELATIONAL_DB=mysql 与 DATABASE_URL 不一致")
        if self.relational_db == "postgresql" and not self.database_url.startswith(
            "postgresql+"
        ):
            raise ValueError("RELATIONAL_DB=postgresql 与 DATABASE_URL 不一致")
        return self

    def sync_database_url(self) -> str:
        """Alembic 等同步脚本：异步 URL 映射为 pymysql / psycopg。"""
        url = self.database_url
        pairs: tuple[tuple[str, str], ...] = (
            ("mysql+aiomysql://", "mysql+pymysql://"),
            ("postgresql+asyncpg://", "postgresql+psycopg://"),
        )
        for async_prefix, sync_prefix in pairs:
            if url.startswith(async_prefix):
                return sync_prefix + url[len(async_prefix) :]
        raise RuntimeError("sync_database_url：未识别的 database_url（校验应已拦截）")


@lru_cache
def get_settings() -> Settings:
    """单例式读取配置；测试时若需换环境变量，可先 `get_settings.cache_clear()`。"""
    return Settings()
