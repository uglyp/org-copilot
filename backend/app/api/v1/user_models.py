"""
当前用户的模型提供商 CRUD、就绪状态查询、连通性探测（probe）。

`PATCH` 采用「删光子模型再重建」的简单策略，前端需提交完整模型列表。
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.entities import LLMModel, LLMProvider, User
from app.services.crypto_keys import decrypt_secret, encrypt_secret
from app.core.config import get_settings
from app.services.default_llm_seed import (
    ensure_deepseek_auto_seed,
    ensure_embedding_api_auto_seed,
    ensure_ollama_chat_seed,
)
from app.services.model_readiness import (
    is_chat_ready,
    is_embedding_ready,
    is_model_ready,
)
from app.services.model_resolver import resolve_default_chat, resolve_default_embedding
from app.services.openai_compat import probe_chat, probe_embedding

router = APIRouter(prefix="/me", tags=["me"])


class ModelIn(BaseModel):
    display_name: str = Field(max_length=128)
    model_id: str = Field(max_length=256)
    purpose: str = Field(pattern="^(chat|embedding)$")
    is_default: bool = False
    enabled: bool = True


class ProviderCreate(BaseModel):
    name: str = Field(max_length=128)
    api_base: str = Field(max_length=512)
    api_key: str
    provider_type: str = "openai_compatible"
    extra_headers: dict[str, str] | None = None
    models: list[ModelIn] = Field(default_factory=list)


class ProviderOut(BaseModel):
    id: int
    name: str
    api_base: str
    provider_type: str
    models: list[dict[str, Any]]

    class Config:
        from_attributes = True


def _is_local_provider(p: LLMProvider) -> bool:
    """与前端「本地 Ollama」判断对齐：名称、常见本机地址与 Ollama 默认端口。"""
    name = (p.name or "").strip().lower()
    if name == "ollama":
        return True
    base = (p.api_base or "").lower()
    if "localhost" in base or "127.0.0.1" in base:
        return True
    if ":11434" in base:
        return True
    return False


def _chat_model_subtitle(m: LLMModel, p: LLMProvider, local: bool) -> str:
    if local:
        return "本地模型 · 需本机 Ollama 运行"
    mid = (m.model_id or "").lower()
    if "think" in mid or "reason" in mid or "reasoning" in mid:
        return "增强推理能力（远程）"
    if m.is_default:
        return "默认对话 · 适合大部分任务"
    return f"远程 API · {p.name}"


class ChatModelOptionOut(BaseModel):
    """对话页可选模型：默认（如 DeepSeek）+ 其它已启用的 chat（如 Ollama）。"""

    id: int
    display_name: str
    model_id: str
    provider_id: int
    provider_name: str
    is_default: bool
    provider_kind: Literal["local", "remote"]
    subtitle: str


@router.get("/chat-models", response_model=list[ChatModelOptionOut])
async def list_chat_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatModelOptionOut]:
    await ensure_deepseek_auto_seed(db, user.id)
    await ensure_ollama_chat_seed(db, user.id)
    q = (
        select(LLMModel, LLMProvider)
        .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
        .where(
            and_(
                LLMProvider.user_id == user.id,
                LLMModel.purpose == "chat",
                LLMModel.enabled.is_(True),
            )
        )
        .order_by(LLMModel.is_default.desc(), LLMProvider.id, LLMModel.id)
    )
    r = await db.execute(q)
    out: list[ChatModelOptionOut] = []
    for m, p in r.all():
        local = _is_local_provider(p)
        out.append(
            ChatModelOptionOut(
                id=m.id,
                display_name=m.display_name,
                model_id=m.model_id,
                provider_id=p.id,
                provider_name=p.name,
                is_default=m.is_default,
                provider_kind="local" if local else "remote",
                subtitle=_chat_model_subtitle(m, p, local),
            )
        )
    return out


@router.get("/model-readiness")
async def model_readiness(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await ensure_deepseek_auto_seed(db, user.id)
    await ensure_embedding_api_auto_seed(db, user.id)
    await ensure_ollama_chat_seed(db, user.id)
    settings = get_settings()
    chat_ok = await is_chat_ready(db, user.id)
    emb_ok = await is_embedding_ready(db, user.id)
    full_ok, missing_full = await is_model_ready(db, user.id)
    missing: list[str] = []
    if not chat_ok:
        missing.append("chat")
    if not emb_ok:
        missing.append("embedding")
    emb_src = (
        "local"
        if settings.use_local_embedding
        else ("api" if emb_ok else "none")
    )
    return {
        "ready": chat_ok,
        "chat_ready": chat_ok,
        "embedding_ready": emb_ok,
        "embedding_source": emb_src,
        "full_stack_ready": full_ok,
        "missing": missing,
        "missing_full_stack": missing_full,
    }


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderOut]:
    r = await db.execute(
        select(LLMProvider).where(LLMProvider.user_id == user.id).order_by(LLMProvider.id)
    )
    providers = list(r.scalars().all())
    out: list[ProviderOut] = []
    for p in providers:
        r2 = await db.execute(select(LLMModel).where(LLMModel.provider_id == p.id))
        models = r2.scalars().all()
        out.append(
            ProviderOut(
                id=p.id,
                name=p.name,
                api_base=p.api_base,
                provider_type=p.provider_type,
                models=[
                    {
                        "id": m.id,
                        "display_name": m.display_name,
                        "model_id": m.model_id,
                        "purpose": m.purpose,
                        "is_default": m.is_default,
                        "enabled": m.enabled,
                    }
                    for m in models
                ],
            )
        )
    return out


async def _clear_defaults(
    db: AsyncSession, provider_id: int, purpose: str
) -> None:
    await db.execute(
        update(LLMModel)
        .where(LLMModel.provider_id == provider_id, LLMModel.purpose == purpose)
        .values(is_default=False)
    )


@router.post("/providers", response_model=ProviderOut)
async def create_provider(
    body: ProviderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    if not (body.api_key or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="api_key is required")
    enc = encrypt_secret(body.api_key.strip())
    p = LLMProvider(
        user_id=user.id,
        name=body.name,
        api_base=body.api_base.rstrip("/"),
        api_key_encrypted=enc,
        provider_type=body.provider_type,
        extra_headers_json=body.extra_headers,
    )
    db.add(p)
    await db.flush()
    for m in body.models:
        if m.is_default:
            await _clear_defaults(db, p.id, m.purpose)
        mm = LLMModel(
            provider_id=p.id,
            display_name=m.display_name,
            model_id=m.model_id,
            purpose=m.purpose,
            is_default=m.is_default,
            enabled=m.enabled,
        )
        db.add(mm)
    await db.flush()
    r2 = await db.execute(select(LLMModel).where(LLMModel.provider_id == p.id))
    models = r2.scalars().all()
    return ProviderOut(
        id=p.id,
        name=p.name,
        api_base=p.api_base,
        provider_type=p.provider_type,
        models=[
            {
                "id": m.id,
                "display_name": m.display_name,
                "model_id": m.model_id,
                "purpose": m.purpose,
                "is_default": m.is_default,
                "enabled": m.enabled,
            }
            for m in models
        ],
    )


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    body: ProviderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    r = await db.execute(
        select(LLMProvider).where(
            LLMProvider.id == provider_id, LLMProvider.user_id == user.id
        )
    )
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    p.name = body.name
    p.api_base = body.api_base.rstrip("/")
    if body.api_key:
        p.api_key_encrypted = encrypt_secret(body.api_key)
    p.provider_type = body.provider_type
    p.extra_headers_json = body.extra_headers
    await db.execute(delete(LLMModel).where(LLMModel.provider_id == p.id))
    await db.flush()
    for m in body.models:
        if m.is_default:
            await _clear_defaults(db, p.id, m.purpose)
        mm = LLMModel(
            provider_id=p.id,
            display_name=m.display_name,
            model_id=m.model_id,
            purpose=m.purpose,
            is_default=m.is_default,
            enabled=m.enabled,
        )
        db.add(mm)
    await db.flush()
    r2 = await db.execute(select(LLMModel).where(LLMModel.provider_id == p.id))
    models = r2.scalars().all()
    return ProviderOut(
        id=p.id,
        name=p.name,
        api_base=p.api_base,
        provider_type=p.provider_type,
        models=[
            {
                "id": m.id,
                "display_name": m.display_name,
                "model_id": m.model_id,
                "purpose": m.purpose,
                "is_default": m.is_default,
                "enabled": m.enabled,
            }
            for m in models
        ],
    )


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    r = await db.execute(
        select(LLMProvider).where(
            LLMProvider.id == provider_id, LLMProvider.user_id == user.id
        )
    )
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    await db.execute(delete(LLMModel).where(LLMModel.provider_id == provider_id))
    await db.execute(
        delete(LLMProvider).where(
            LLMProvider.id == provider_id, LLMProvider.user_id == user.id
        )
    )
    return {"status": "ok"}


@router.post("/providers/{provider_id}/probe")
async def probe_provider(
    provider_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    r = await db.execute(
        select(LLMProvider).where(
            LLMProvider.id == provider_id, LLMProvider.user_id == user.id
        )
    )
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    from app.services.model_resolver import ResolvedOpenAICompat

    api_key = decrypt_secret(p.api_key_encrypted)
    r2 = await db.execute(
        select(LLMModel).where(
            LLMModel.provider_id == p.id,
            LLMModel.enabled.is_(True),
        )
    )
    models = list(r2.scalars().all())
    chat_m = next((m for m in models if m.purpose == "chat" and m.is_default), None)
    emb_m = next((m for m in models if m.purpose == "embedding" and m.is_default), None)
    if not chat_m:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="该提供商下需配置一个默认的对话（chat）模型后再探测",
        )
    extra = p.extra_headers_json or {}
    headers = {str(k): str(v) for k, v in extra.items()} if extra else None
    chat_cfg = ResolvedOpenAICompat(
        api_base=p.api_base,
        api_key=api_key,
        model_id=chat_m.model_id,
        extra_headers=headers,
    )
    await probe_chat(chat_cfg)
    if emb_m:
        emb_cfg = ResolvedOpenAICompat(
            api_base=p.api_base,
            api_key=api_key,
            model_id=emb_m.model_id,
            extra_headers=headers,
        )
        await probe_embedding(emb_cfg)
    return {"status": "ok"}
