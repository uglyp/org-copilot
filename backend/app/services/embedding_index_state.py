"""
向量索引与嵌入模型一致性：指纹 + 维度检测、入库后写入元数据、管理员一键重建。

Milvus 集合为实例级共享；重建会删除当前集合并全量重跑「就绪」文档的入库流水线。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.entities import Document, EmbeddingIndexMeta, LLMModel, LLMProvider

logger = logging.getLogger(__name__)

SINGLETON_ID = 1


async def _default_embedding_model_row(
    session: AsyncSession, user_id: int
) -> LLMModel | None:
    q = (
        select(LLMModel)
        .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
        .where(
            and_(
                LLMProvider.user_id == user_id,
                LLMModel.purpose == "embedding",
                LLMModel.is_default.is_(True),
                LLMModel.enabled.is_(True),
            )
        )
        .limit(1)
    )
    r = await session.execute(q)
    return r.scalar_one_or_none()


def expected_fingerprint(settings: Settings, emb_row: LLMModel | None) -> str:
    """不发起网络请求；与当前配置及（远程时）默认 embedding 模型行一致。"""
    if settings.use_local_embedding:
        return f"local:{settings.local_embedding_model.strip()}"
    if emb_row is None:
        return "none"
    mid = (emb_row.model_id or "").strip()
    return f"api:{emb_row.id}:{mid}"


async def get_meta_row(session: AsyncSession) -> EmbeddingIndexMeta | None:
    r = await session.execute(
        select(EmbeddingIndexMeta).where(EmbeddingIndexMeta.id == SINGLETON_ID)
    )
    return r.scalar_one_or_none()


async def upsert_embedding_index_meta(
    session: AsyncSession, fingerprint: str, vector_dim: int
) -> None:
    now = datetime.now(timezone.utc)
    row = await get_meta_row(session)
    if row:
        row.fingerprint = fingerprint[:512]
        row.vector_dim = int(vector_dim)
        row.updated_at = now
    else:
        session.add(
            EmbeddingIndexMeta(
                id=SINGLETON_ID,
                fingerprint=fingerprint[:512],
                vector_dim=int(vector_dim),
                updated_at=now,
            )
        )


async def sync_meta_after_successful_ingest(
    session: AsyncSession,
    *,
    kb_owner_user_id: int,
    vector_dim: int,
) -> None:
    """文档入库成功并已写入 Milvus 后调用，刷新单例元数据。"""
    settings = get_settings()
    emb_row = None
    if not settings.use_local_embedding:
        emb_row = await _default_embedding_model_row(session, kb_owner_user_id)
    fp = expected_fingerprint(settings, emb_row)
    await upsert_embedding_index_meta(session, fp, vector_dim)


async def light_mismatch_hints(
    session: AsyncSession, user_id: int
) -> tuple[bool, list[str]]:
    """轻量检测（无 embedding 网络请求），供高频接口如 model-readiness 使用。"""
    settings = get_settings()
    emb_row = None
    if not settings.use_local_embedding:
        emb_row = await _default_embedding_model_row(session, user_id)
    exp = expected_fingerprint(settings, emb_row)
    meta = await get_meta_row(session)
    from app.services.milvus_store import get_collection_vector_dim

    milvus_dim = get_collection_vector_dim()
    reasons: list[str] = []
    if meta:
        if meta.fingerprint != exp:
            reasons.append(
                "当前向量配置（本地 fastembed 或默认 embedding 模型）与上次入库记录不一致，"
                "需重建索引后检索结果才可靠。"
            )
        if milvus_dim is not None and meta.vector_dim != milvus_dim:
            reasons.append(
                "Milvus 集合维度与库内记录不一致，可能手动改动过向量库，建议重建索引。"
            )
    return (len(reasons) > 0, reasons)


async def full_status(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """含一次真实 embed 探测维度，供模型设置页展示。"""
    from app.services.model_resolver import resolve_default_embedding
    from app.services.milvus_store import get_collection_vector_dim
    from app.services.openai_compat import embed_texts

    settings = get_settings()
    emb_row = None
    if not settings.use_local_embedding:
        emb_row = await _default_embedding_model_row(session, user_id)
    exp_fp = expected_fingerprint(settings, emb_row)
    meta = await get_meta_row(session)
    milvus_dim = get_collection_vector_dim()

    probe_dim: int | None = None
    probe_error: str | None = None
    if settings.use_local_embedding or await _embedding_cfg_available(
        session, user_id, settings
    ):
        try:
            cfg = await resolve_default_embedding(session, user_id)
            vecs, _ = await embed_texts(cfg, ["org-copilot embedding probe"])
            if vecs and vecs[0]:
                probe_dim = len(vecs[0])
        except Exception as e:  # noqa: BLE001
            probe_error = str(e)[:500]

    mismatch_light, hints = await light_mismatch_hints(session, user_id)
    dim_mismatch = (
        milvus_dim is not None
        and probe_dim is not None
        and milvus_dim != probe_dim
    )
    needs_rebuild = mismatch_light or dim_mismatch

    return {
        "milvus_collection": settings.milvus_collection,
        "use_local_embedding": settings.use_local_embedding,
        "expected_fingerprint": exp_fp,
        "stored_fingerprint": meta.fingerprint if meta else None,
        "stored_vector_dim": meta.vector_dim if meta else None,
        "stored_updated_at": meta.updated_at.isoformat() if meta else None,
        "milvus_vector_dim": milvus_dim,
        "probe_vector_dim": probe_dim,
        "probe_error": probe_error,
        "embedding_index_needs_rebuild": needs_rebuild,
        "reasons": hints
        + (
            [
                f"Milvus 中向量维度为 {milvus_dim}，当前嵌入模型输出为 {probe_dim}，无法共用同一集合。"
            ]
            if dim_mismatch
            else []
        ),
    }


async def _embedding_cfg_available(
    session: AsyncSession, user_id: int, settings: Settings
) -> bool:
    if settings.use_local_embedding:
        return True
    row = await _default_embedding_model_row(session, user_id)
    return row is not None


async def admin_rebuild_embedding_index(session: AsyncSession, admin_user_id: int) -> dict[str, Any]:
    """删除当前 Milvus 集合并对所有 status=ready 文档重新入库。调用方须已校验管理员。"""
    from app.services.model_resolver import resolve_default_embedding
    from app.services.milvus_store import get_milvus
    from app.workers.tasks import ingest_document_task

    settings = get_settings()
    cfg = await resolve_default_embedding(session, admin_user_id)
    if not settings.use_local_embedding and not cfg:
        raise ValueError("未配置默认向量模型，无法重建索引")

    from app.services.openai_compat import embed_texts

    vecs, _ = await embed_texts(cfg, ["org-copilot rebuild dim probe"])
    if not vecs or not vecs[0]:
        raise ValueError("探测嵌入维度失败")
    dim = len(vecs[0])

    client = get_milvus()
    name = settings.milvus_collection
    if client.has_collection(name):
        client.drop_collection(collection_name=name)
        logger.warning("已删除 Milvus 集合 %s，开始全量重建向量", name)

    r = await session.execute(
        select(Document.id).where(Document.status == "ready").order_by(Document.id)
    )
    doc_ids = [row[0] for row in r.all()]
    ok, err = 0, 0
    last_err: str | None = None
    for doc_id in doc_ids:
        try:
            await ingest_document_task(doc_id)
            ok += 1
        except Exception as e:  # noqa: BLE001
            err += 1
            logger.exception("重建索引时文档 id=%s 入库失败", doc_id)
            last_err = str(e)[:300]

    emb_row = None
    if not settings.use_local_embedding:
        emb_row = await _default_embedding_model_row(session, admin_user_id)
    fp = expected_fingerprint(settings, emb_row)
    await upsert_embedding_index_meta(session, fp, dim)
    await session.flush()

    out: dict[str, Any] = {
        "dropped_collection": name,
        "documents_total": len(doc_ids),
        "documents_succeeded": ok,
        "documents_failed": err,
        "recorded_fingerprint": fp,
        "recorded_vector_dim": dim,
    }
    if err and last_err:
        out["last_error_hint"] = last_err
    return out
