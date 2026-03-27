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
    """终端用户：登录名唯一，密码仅存哈希。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
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
    """知识库：用户隔离；文档与向量检索均带 `kb_id` 过滤。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    owner: Mapped[User] = relationship(back_populates="knowledge_bases")
    documents: Mapped[list[Document]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class Document(Base):
    """上传的原始文件元数据；`status` 跟踪解析/向量化流水线。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    storage_path: Mapped[str] = mapped_column(String(1024))
    modality: Mapped[str] = mapped_column(String(16), default="text")  # text | image
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued,processing,ready,failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """文本块：RAG 检索与引用的最小单位；`qdrant_point_id` 与向量库中的点 id 对应。"""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    modality: Mapped[str] = mapped_column(String(16), default="text")  # text | image
    extra_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    qdrant_point_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

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
