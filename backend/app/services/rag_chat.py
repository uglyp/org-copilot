"""
RAG 对话核心：向量检索（Milvus）→ 拼上下文 → 调 LLM 流式输出 → 落库助手消息与引用。

数据流简述：
1. 用户问题做 embedding，在指定 `kb_id` 下做近邻搜索得到若干 chunk。
2. `_build_context_from_hits`：优先读 MySQL `Chunk` 全文；缺失时用 Milvus 命中里的 `text` 兜底。
3. 将片段与近期历史一并塞进 chat messages，要求模型严格依据片段回答。
4. `asyncio.to_thread(search_kb)`：pymilvus 客户端为同步 API，放到线程池避免阻塞 asyncio 事件循环。
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import Chunk, LlmUsageRecord, Message, User
from app.services.permissions import (
    document_visible_to,
    is_user_admin,
    load_documents_for_acl_check,
)
from app.services.model_resolver import (
    resolve_chat_model,
    resolve_default_embedding,
)
from app.services.openai_compat import chat_completion_stream, embed_texts
from app.services.milvus_store import search_kb
from app.services.usage_tokens import (
    estimate_chat_completion_tokens,
    estimate_chat_prompt_tokens,
    infer_endpoint_kind,
    parse_openai_usage,
)

logger = logging.getLogger(__name__)


def _sse(data: dict[str, Any]) -> str:
    """SSE 一行一个 JSON 事件（与前端解析约定一致）。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _build_context_from_hits(
    session: AsyncSession,
    hits: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """把向量检索结果转成「模型可读上下文」+「结构化引用列表」。

    `chunk_db_id` / `chunk_id`：历史上 payload 字段名可能不一致，这里做兼容。
    """
    if not hits:
        return [], []

    raw_ids: list[int] = []
    for h in hits:
        pl = h.get("payload") or {}
        cid = pl.get("chunk_db_id") if pl.get("chunk_db_id") is not None else pl.get("chunk_id")
        if cid is not None:
            raw_ids.append(int(cid))

    seen: set[int] = set()
    chunk_ids: list[int] = []
    for cid in raw_ids:
        if cid not in seen:
            seen.add(cid)
            chunk_ids.append(cid)

    rows: dict[int, Chunk] = {}
    if chunk_ids:
        r = await session.execute(select(Chunk).where(Chunk.id.in_(chunk_ids)))
        rows = {c.id: c for c in r.scalars().all()}

    context_parts: list[str] = []
    citations: list[dict[str, Any]] = []
    seen_ctx: set[int] = set()

    for h in hits:
        pl = h.get("payload") or {}
        cid_raw = pl.get("chunk_db_id") if pl.get("chunk_db_id") is not None else pl.get("chunk_id")
        if cid_raw is None:
            continue
        cid = int(cid_raw)
        if cid in seen_ctx:
            continue

        ch = rows.get(cid)
        content: str | None = ch.content if ch is not None else None
        if not content and pl.get("text"):
            content = str(pl["text"])
        if not content:
            continue

        seen_ctx.add(cid)
        fn = pl.get("filename") or "?"
        modality = "text"
        if ch is not None and getattr(ch, "modality", None):
            modality = ch.modality
        elif pl.get("modality"):
            modality = str(pl["modality"])
        prefix = "[图像/OCR] " if modality == "image" else ""
        context_parts.append(f"{prefix}[片段 id={cid} 来源文件={fn}] {content}")

        cit: dict[str, Any] = {
            "chunk_id": cid,
            "doc_id": ch.doc_id if ch is not None else pl.get("doc_id"),
            "excerpt": content[:500],
            "source": "mysql_chunk" if ch is not None else "milvus_entity",
            "modality": modality,
        }
        citations.append(cit)

    return context_parts, citations


async def _filter_hits_by_document_acl(
    session: AsyncSession,
    hits: list[dict[str, Any]],
    acl_user: User,
    *,
    public_branch_label: str,
) -> list[dict[str, Any]]:
    """第三层：按关系库文档元数据过滤（分行/密级/部门）。与列表接口一致；Milvus 层 ACL 为额外收紧，不能替代本步。"""
    if is_user_admin(acl_user):
        return hits
    doc_ids: list[int] = []
    for h in hits:
        pl = h.get("payload") or {}
        did = pl.get("doc_id")
        if did is not None:
            doc_ids.append(int(did))
    if not doc_ids:
        return hits
    docs = await load_documents_for_acl_check(session, list(dict.fromkeys(doc_ids)))
    out: list[dict[str, Any]] = []
    for h in hits:
        pl = h.get("payload") or {}
        did = pl.get("doc_id")
        if did is None:
            continue
        doc = docs.get(int(did))
        if doc is None:
            continue
        if document_visible_to(doc, acl_user, public_branch_label=public_branch_label):
            out.append(h)
    return out


async def stream_chat_reply(
    session: AsyncSession,
    *,
    user_id: int,
    kb_id: int,
    conversation_id: int,
    user_text: str,
    user_message_id: int,
    acl_user: User,
    top_k: int | None = None,
    chat_model_id: int | None = None,
    request_id: str | None = None,
) -> AsyncIterator[str]:
    """异步生成器：`yield` 字符串片段（已格式化为 SSE 行），供 `StreamingResponse` 消费。"""
    settings = get_settings()
    if top_k is None:
        top_k = settings.rag_top_k
    emb_cfg = await resolve_default_embedding(session, user_id)
    chat_cfg = await resolve_chat_model(session, user_id, chat_model_id)
    if not chat_cfg:
        yield _sse({"type": "error", "code": "CHAT_MODEL_NOT_READY"})
        return

    logger.info(
        "rag_chat_start request_id=%s user_id=%s conversation_id=%s kb_id=%s chat_model_id=%s",
        request_id or "-",
        user_id,
        conversation_id,
        kb_id,
        chat_model_id,
    )
    yield _sse({"type": "status", "phase": "embedding"})

    hits: list[dict[str, Any]] = []
    can_retrieve = settings.use_local_embedding or bool(emb_cfg)
    embed_pt: int | None = None
    embed_tt: int | None = None
    embed_est = False
    if can_retrieve:
        try:
            q_emb, eu = await embed_texts(emb_cfg, [user_text])
            embed_pt, embed_tt = eu.prompt_tokens, eu.total_tokens
            embed_est = eu.is_estimated
            logger.info(
                "rag_chat_phase request_id=%s phase=searching conversation_id=%s kb_id=%s",
                request_id or "-",
                conversation_id,
                kb_id,
            )
            yield _sse({"type": "status", "phase": "searching"})
            # embed_texts 返回的是「每条文本一个向量」的列表；search_kb 需要单个 float 向量
            if not q_emb:
                raise ValueError("embedding 未返回向量")
            # 向量检索多取一些，再经文档 ACL 过滤后截断，避免 Milvus 未带 ACL 或部门过滤后条数过少
            search_limit = min(max(top_k * 3, top_k), 50)
            acl_kw: User | None = acl_user if settings.enterprise_acl_enabled else None
            # pymilvus 为同步 IO，放在线程池避免长时间卡住 asyncio 事件循环
            hits = await asyncio.to_thread(
                search_kb,
                kb_id,
                q_emb[0],
                search_limit,
                acl_user=acl_kw,
            )
            hits = await _filter_hits_by_document_acl(
                session,
                hits,
                acl_user,
                public_branch_label=settings.public_branch_label,
            )
            hits = hits[:top_k]
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "rag_chat_search_failed request_id=%s conversation_id=%s kb_id=%s",
                request_id or "-",
                conversation_id,
                kb_id,
            )
            yield _sse(
                {
                    "type": "error",
                    "code": f"知识库检索失败（向量或 Milvus）：{str(e)[:400]}",
                }
            )
            return

    context_parts, citations = await _build_context_from_hits(session, hits)

    if not context_parts:
        if can_retrieve:
            context_parts.append(
                "(知识库中未检索到相关片段。请明确告知用户未命中，并避免编造事实。)"
            )
        else:
            context_parts.append(
                "(当前未配置向量能力，无法检索知识库；请直接根据常识回答用户问题，并说明无法访问知识库。)"
            )

    history_msgs = await _load_history(
        session, conversation_id, limit=10, before_message_id=user_message_id
    )

    system = (
        "你是知识库问答助手。请严格依据下方「知识库片段」作答。\n"
        "若片段中含 Markdown 表格、列表（例如「推荐技术栈」中的前端/后端/语言），请从中归纳事实后再回答。\n"
        "仅当片段中确实没有与问题相关的信息时，再明确说明「知识库片段中未找到」，不要编造。\n"
        "不要编造片段中不存在的事实。"
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    messages.append({"role": "system", "content": "知识库片段：\n" + "\n\n".join(context_parts)})
    for m in history_msgs:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": user_text})

    logger.info(
        "rag_chat_phase request_id=%s phase=generating conversation_id=%s kb_id=%s hits=%s",
        request_id or "-",
        conversation_id,
        kb_id,
        len(hits),
    )
    yield _sse({"type": "status", "phase": "generating"})

    full: list[str] = []
    chat_usage_raw: dict[str, Any] | None = None
    try:
        async for item in chat_completion_stream(chat_cfg, messages):
            if isinstance(item, dict) and "usage" in item:
                chat_usage_raw = item["usage"] if isinstance(item["usage"], dict) else None
                continue
            full.append(str(item))
            yield _sse({"type": "token", "content": str(item)})
    except httpx.HTTPStatusError as e:
        logger.exception(
            "rag_chat_http_status_error request_id=%s conversation_id=%s status=%s",
            request_id or "-",
            conversation_id,
            e.response.status_code,
        )
        hint = ""
        if e.response.status_code == 404 and "11434" in str(chat_cfg.api_base):
            hint = "（请确认本机已启动 Ollama，且版本支持 OpenAI 兼容接口 /v1/chat/completions；API Base 填 http://127.0.0.1:11434 或 http://127.0.0.1:11434/v1 均可）"
        body = ""
        try:
            body = (e.response.text or "")[:280]
        except Exception:
            pass
        msg = f"对话 API HTTP {e.response.status_code}{f'：{body}' if body else ''}{hint}"
        yield _sse({"type": "error", "code": msg[:900]})
        return
    except httpx.RequestError as e:
        logger.exception(
            "rag_chat_request_error request_id=%s conversation_id=%s",
            request_id or "-",
            conversation_id,
        )
        yield _sse(
            {
                "type": "error",
                "code": f"无法连接对话服务（{chat_cfg.api_base}）：{e!s}"[:900],
            }
        )
        return

    assistant_text = "".join(full)
    pt, ct, tt = parse_openai_usage(chat_usage_raw)
    chat_est = False
    if not chat_usage_raw:
        chat_est = True
    if pt is None:
        pt = estimate_chat_prompt_tokens(messages)
        if chat_usage_raw:
            chat_est = True
    if ct is None:
        ct = estimate_chat_completion_tokens(assistant_text)
        if chat_usage_raw:
            chat_est = True
    if tt is None:
        tt = pt + ct
        if chat_usage_raw:
            chat_est = True

    asst = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=assistant_text,
        citations_json=citations,
    )
    session.add(asst)
    await session.flush()

    session.add(
        LlmUsageRecord(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=asst.id,
            chat_model_id=chat_cfg.llm_model_id,
            endpoint_kind=infer_endpoint_kind(chat_cfg.api_base),
            embed_prompt_tokens=embed_pt if can_retrieve else None,
            embed_total_tokens=embed_tt if can_retrieve else None,
            chat_prompt_tokens=pt,
            chat_completion_tokens=ct,
            chat_total_tokens=tt,
            embed_is_estimated=embed_est if can_retrieve else False,
            chat_is_estimated=chat_est,
        )
    )

    usage_out: dict[str, Any] = {
        "endpoint_kind": infer_endpoint_kind(chat_cfg.api_base),
        "embed_prompt_tokens": embed_pt if can_retrieve else None,
        "embed_total_tokens": embed_tt if can_retrieve else None,
        "embed_is_estimated": embed_est if can_retrieve else False,
        "chat_prompt_tokens": pt,
        "chat_completion_tokens": ct,
        "chat_total_tokens": tt,
        "chat_is_estimated": chat_est,
    }
    logger.info(
        "rag_chat_done request_id=%s conversation_id=%s assistant_message_id=%s chat_total_tokens=%s",
        request_id or "-",
        conversation_id,
        asst.id,
        tt,
    )
    yield _sse(
        {
            "type": "done",
            "citations": citations,
            "full_text": assistant_text,
            "message_id": asst.id,
            "usage": usage_out,
        }
    )


async def _load_history(
    session: AsyncSession,
    conversation_id: int,
    limit: int,
    before_message_id: int | None = None,
) -> list[Message]:
    """取当前用户消息之前的若干条，按时间正序；`before_message_id` 排除本轮刚写入的用户消息。"""
    q = select(Message).where(Message.conversation_id == conversation_id)
    if before_message_id is not None:
        q = q.where(Message.id < before_message_id)
    r = await session.execute(q.order_by(Message.id.desc()).limit(limit))
    rows = list(r.scalars().all())
    rows.reverse()
    return [m for m in rows if m.role in ("user", "assistant")]
