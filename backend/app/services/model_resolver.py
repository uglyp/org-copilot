"""
从数据库解析「当前用户的默认 chat / embedding 模型」为可调用配置。

`ResolvedOpenAICompat` 是纯数据类（`dataclass`），便于在各服务间传递，不含 ORM 会话。
"""

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import LLMModel, LLMProvider
from app.services.crypto_keys import decrypt_secret


@dataclass
class ResolvedOpenAICompat:
    """一次 API 调用所需：网关地址、密钥、模型名、可选额外 Header（如部分云厂商要求）。"""
    api_base: str
    api_key: str
    model_id: str
    extra_headers: dict[str, str] | None


async def resolve_default_chat(session: AsyncSession, user_id: int) -> ResolvedOpenAICompat | None:
    row = await _resolve_default(session, user_id, "chat")
    return row


async def resolve_chat_model(
    session: AsyncSession,
    user_id: int,
    chat_model_id: int | None,
) -> ResolvedOpenAICompat | None:
    """指定 `llm_models.id` 时用该 chat 模型；否则用默认 chat（通常为 DeepSeek）。"""
    if chat_model_id is None:
        return await resolve_default_chat(session, user_id)
    q = (
        select(LLMModel, LLMProvider)
        .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
        .where(
            and_(
                LLMProvider.user_id == user_id,
                LLMModel.id == chat_model_id,
                LLMModel.purpose == "chat",
                LLMModel.enabled.is_(True),
            )
        )
        .limit(1)
    )
    r = await session.execute(q)
    tup = r.first()
    if not tup:
        return None
    m, p = tup
    api_key = decrypt_secret(p.api_key_encrypted)
    extra = p.extra_headers_json or {}
    headers = {str(k): str(v) for k, v in extra.items()} if extra else None
    return ResolvedOpenAICompat(
        api_base=p.api_base.rstrip("/"),
        api_key=api_key,
        model_id=(m.model_id or "").strip(),
        extra_headers=headers,
    )


async def resolve_default_embedding(session: AsyncSession, user_id: int) -> ResolvedOpenAICompat | None:
    return await _resolve_default(session, user_id, "embedding")


async def _resolve_default(
    session: AsyncSession, user_id: int, purpose: str
) -> ResolvedOpenAICompat | None:
    q = (
        select(LLMModel, LLMProvider)
        .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
        .where(
            and_(
                LLMProvider.user_id == user_id,
                LLMModel.purpose == purpose,
                LLMModel.is_default.is_(True),
                LLMModel.enabled.is_(True),
            )
        )
        .limit(1)
    )
    r = await session.execute(q)
    tup = r.first()
    if not tup:
        return None
    m, p = tup
    api_key = decrypt_secret(p.api_key_encrypted)
    extra = p.extra_headers_json or {}
    headers = {str(k): str(v) for k, v in extra.items()} if extra else None
    return ResolvedOpenAICompat(
        api_base=p.api_base.rstrip("/"),
        api_key=api_key,
        model_id=(m.model_id or "").strip(),
        extra_headers=headers,
    )
