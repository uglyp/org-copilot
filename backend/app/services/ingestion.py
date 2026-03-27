"""
文档入库：读文件 → 抽文本 → 固定窗口分块 → 批量 embedding → 写 MySQL `Chunk` + Qdrant 向量点。

失败路径必须 `rollback` 后再查 `Document` 更新 `failed`，否则 session 处于「待回滚」状态会抛 `PendingRollbackError`。
"""

import logging
import os
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.hf_env import configure_hf_hub_env
from app.models.entities import Chunk, Document, KnowledgeBase
from app.services.document_extract import extract_text_from_file
from app.services.image_ingest import is_image_path, ocr_image_to_canonical
from app.services.model_resolver import resolve_default_embedding
from app.services.openai_compat import embed_texts
from app.services.qdrant_store import delete_by_doc_id, upsert_chunks
from app.services.text_chunking import chunk_text

logger = logging.getLogger(__name__)


async def process_document_ingestion(session: AsyncSession, doc_id: int) -> None:
    """单文档完整流水线；由 `workers.tasks.ingest_document_task` 在独立 session 里调用并 commit。"""
    # 与 `main.py` 入口解耦时（如单独脚本）也保证 fastembed 能读到 HF_ENDPOINT 等镜像
    configure_hf_hub_env()

    r = await session.execute(select(Document).where(Document.id == doc_id))
    doc = r.scalar_one_or_none()
    if not doc:
        logger.warning(
            "ingestion: 文档 id=%s 在库中不存在，跳过（上传接口须先 commit 再调度后台任务）",
            doc_id,
        )
        return

    r2 = await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.kb_id))
    kb = r2.scalar_one_or_none()
    if not kb:
        doc.status = "failed"
        doc.error_message = "Knowledge base missing"
        await session.flush()
        return

    settings = get_settings()
    cfg = await resolve_default_embedding(session, kb.user_id)
    if not settings.use_local_embedding and not cfg:
        doc.status = "failed"
        doc.error_message = "No embedding model configured (启用 USE_LOCAL_EMBEDDING 或在模型设置中配置默认向量模型)"
        await session.flush()
        return

    doc.status = "processing"
    await session.flush()

    try:
        if not os.path.isfile(doc.storage_path):
            raise FileNotFoundError(doc.storage_path)

        extra_base: dict | None = None
        if doc.modality == "image" or is_image_path(doc.storage_path):
            canonical, extra_base = ocr_image_to_canonical(
                doc.storage_path, filename=doc.filename
            )
            raw = canonical
            doc.modality = "image"
        else:
            raw = extract_text_from_file(doc.storage_path)
        parts = chunk_text(raw)
        if not parts:
            doc.status = "failed"
            doc.error_message = "No text extracted"
            await session.flush()
            return

        await session.execute(delete(Chunk).where(Chunk.doc_id == doc.id))
        await session.flush()
        delete_by_doc_id(doc.id)

        embeddings = await embed_texts(cfg, parts)

        chunk_modality = "image" if doc.modality == "image" else "text"
        new_chunks: list[Chunk] = []
        for idx, text in enumerate(parts):
            # qdrant_point_id 有唯一索引；flush 前每条占位必须不同，写入 Qdrant 后再更新为真实 point id
            ch = Chunk(
                doc_id=doc.id,
                kb_id=doc.kb_id,
                chunk_index=idx,
                content=text,
                modality=chunk_modality,
                extra_json=extra_base if chunk_modality == "image" else None,
                qdrant_point_id=str(uuid.uuid4()),
            )
            session.add(ch)
            new_chunks.append(ch)
        await session.flush()

        db_ids = [c.id for c in new_chunks]
        payloads = [
            {
                "text": t[:2000],
                "chunk_index": i,
                "chunk_db_id": db_ids[i],
                "filename": doc.filename,
                "modality": chunk_modality,
            }
            for i, t in enumerate(parts)
        ]
        point_ids = upsert_chunks(
            doc.kb_id,
            doc.id,
            embeddings,
            payloads,
            db_ids,
        )
        for ch, pid in zip(new_chunks, point_ids, strict=True):
            ch.qdrant_point_id = pid

        doc.status = "ready"
        doc.error_message = None
        await session.flush()
    except Exception as e:  # noqa: BLE001
        err = str(e)[:2000]
        logger.exception("文档 id=%s 入库失败", doc_id)
        # flush 失败（如唯一键冲突）后 session 已失效，须 rollback 再更新 failed，避免 PendingRollbackError
        try:
            await session.rollback()
        except Exception:
            pass
        r = await session.execute(select(Document).where(Document.id == doc_id))
        doc2 = r.scalar_one_or_none()
        if doc2:
            doc2.status = "failed"
            doc2.error_message = err
            await session.flush()
