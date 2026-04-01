"""删除知识库时清理会话、文档、分块、Milvus 与磁盘文件，避免外键阻塞与孤儿数据。"""

from __future__ import annotations

import os

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Chunk, Conversation, Document, KnowledgeBase, Message
from app.services.milvus_store import delete_by_doc_id


async def purge_knowledge_base(db: AsyncSession, kb_id: int) -> None:
    """删除指定知识库及其下全部数据（含绑定会话、向量与上传文件）。"""
    r = await db.execute(select(Conversation.id).where(Conversation.kb_id == kb_id))
    conv_ids = [row[0] for row in r.all()]
    if conv_ids:
        await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))

    r = await db.execute(select(Document).where(Document.kb_id == kb_id))
    for doc in r.scalars().all():
        delete_by_doc_id(doc.id)
        await db.execute(delete(Chunk).where(Chunk.doc_id == doc.id))
        try:
            if doc.storage_path and os.path.isfile(doc.storage_path):
                os.remove(doc.storage_path)
        except OSError:
            pass
        await db.execute(delete(Document).where(Document.id == doc.id))

    await db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb_id))
