"""
SQLAlchemy ORM 实体（表一行 ↔ Python 一个实例）。

- `Mapped[T]`：列类型提示；`relationship` 描述表间一对多/多一，可选 `cascade` 级联删除子表。
- 外键 `ForeignKey`：数据库层引用完整性；`ondelete="CASCADE"` 在部分表上用于删除提供商时删模型。

业务域：用户 → 知识库/文档/分块、LLM 提供商与模型、会话与消息；`Message.citations_json` 存 RAG 引用列表。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """终端用户：登录名唯一，密码仅存哈希。

    企业权限：`branch` / `security_level` / `departments_json` 等用于文档级 ACL 与 JWT 载荷。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    # 企业 ACL：分行标识；「公共」表示全行可见文档所在分支标签
    branch: Mapped[str] = mapped_column(String(128), default="公共")
    role: Mapped[str] = mapped_column(String(64), default="user")
    # 用户可访问的文档密级上限（1～4，越大可访问越高密级文档，要求 doc.security_level <= 该值）
    security_level: Mapped[int] = mapped_column(Integer, default=4)
    departments_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    knowledge_bases: Mapped[list[KnowledgeBase]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    llm_providers: Mapped[list[LLMProvider]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    documents_created: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="creator",
        foreign_keys="Document.creator_user_id",
    )


class PasswordResetToken(Base):
    """一次性重置口令：仅存 token 的 SHA256 十六进制，不存明文。"""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="password_reset_tokens")


class LLMProvider(Base):
    """OpenAI 兼容 API 的一个「账户」：base_url + 加密后的 api_key，下挂多个 `LLMModel`。"""

    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    api_base: Mapped[str] = mapped_column(String(512))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    provider_type: Mapped[str] = mapped_column(String(64), default="openai_compatible")
    extra_headers_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User | None] = relationship(back_populates="llm_providers")
    models: Mapped[list[LLMModel]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


class LLMModel(Base):
    """同一提供商下的具体模型；`purpose` 区分对话 chat 与向量 embedding，`is_default` 每种用途至多一个默认。"""

    __tablename__ = "llm_models"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(128))
    model_id: Mapped[str] = mapped_column(String(256))
    purpose: Mapped[str] = mapped_column(String(32))  # chat | embedding
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    provider: Mapped[LLMProvider] = relationship(back_populates="models")


class KnowledgeBase(Base):
    """知识库：默认属主隔离；可选 `is_org_shared` + `org_id` 供同组织只读协作。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_org_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    owner: Mapped[User] = relationship(back_populates="knowledge_bases")
    documents: Mapped[list[Document]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class Document(Base):
    """上传的原始文件元数据；`status` 跟踪解析/向量化流水线。

    企业 ACL：`branch` / `security_level` / `department` 与 Milvus 标量及 JWT 检索过滤一致。
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    modality: Mapped[str] = mapped_column(String(16), default="text")  # text | image
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued,processing,ready,failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch: Mapped[str] = mapped_column(String(128), default="公共")
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    security_level: Mapped[int] = mapped_column(Integer, default=1)
    creator_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    creator: Mapped[User | None] = relationship(
        back_populates="documents_created",
        foreign_keys=[creator_user_id],
    )
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """文本块：RAG 检索与引用的最小单位；`milvus_point_id` 与 Milvus 集合主键 pk 对应。"""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    modality: Mapped[str] = mapped_column(String(16), default="text")  # text | image
    extra_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    milvus_point_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Conversation(Base):
    """会话：绑定一个知识库，消息历史用于多轮对话上下文。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    """一条对话；助手消息可带 `citations_json`（chunk 摘要等），供前端展示引用。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class LlmUsageRecord(Base):
    """单次用户问答轮次：检索侧 embedding + 对话 completion 的 token 用量（API 或估算）。"""

    __tablename__ = "llm_usage_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    assistant_message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    chat_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id", ondelete="SET NULL"), nullable=True, index=True
    )
    endpoint_kind: Mapped[str] = mapped_column(String(16))  # local | remote

    embed_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embed_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chat_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chat_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chat_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    embed_is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    chat_is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLog(Base):
    """审计占位：可记录谁在何时对何种资源做了什么（扩展用）。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(256))
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SysOrganization(Base):
    """系统管理：组织（与 `User.org_id` / 知识库 `org_id` 字符串对齐）。"""

    __tablename__ = "sys_organizations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SysBranch(Base):
    """系统管理：分行/机构标签（与文档与用户 `branch` 字符串对齐）。"""

    __tablename__ = "sys_branches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SysDepartment(Base):
    """系统管理：部门编码（与用户 `departments_json`、文档 `department` 对齐）。"""

    __tablename__ = "sys_departments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    org_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SysRole(Base):
    """系统管理：角色标识（与 `User.role` 字符串对齐）。"""

    __tablename__ = "sys_roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SysSecurityLevel(Base):
    """系统管理：密级展示名（业务仍使用 1～4 整数）。"""

    __tablename__ = "sys_security_levels"

    level: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
