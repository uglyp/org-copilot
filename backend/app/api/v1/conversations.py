"""
会话与消息 API。

流式回复使用 **SSE**（`text/event-stream`）：`data: {json}\n\n` 逐条推送 token / status / done。
浏览器用 `fetch` + `ReadableStream` 解析（见前端 `api/sse.ts`）；首包先发注释行避免代理缓冲。
"""

from typing import Any
from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_chat_ready
from app.db.session import get_db
from app.models.entities import Conversation, KnowledgeBase, Message, User
from app.services.model_resolver import resolve_chat_model
from app.services.permissions import kb_access_filter
from app.services.rag_chat import stream_chat_reply

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConvCreate(BaseModel):
    kb_id: int
    title: str | None = Field(None, max_length=512)


class ConvOut(BaseModel):
    id: int
    kb_id: int
    title: str | None

    class Config:
        from_attributes = True


class MessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    # 不传或 null：使用默认对话模型（通常为 DeepSeek）；传 `llm_models.id`：使用对应 chat（如 Ollama）
    chat_model_id: int | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations_json: list[dict[str, Any]] | None = None

    class Config:
        from_attributes = True


@router.get("", response_model=list[ConvOut])
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Conversation]:
    r = await db.execute(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.id.desc())
    )
    return list(r.scalars().all())


@router.post("", response_model=ConvOut)
async def create_conversation(
    body: ConvCreate,
    user: User = Depends(require_chat_ready),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    r = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == body.kb_id,
            kb_access_filter(user),
        )
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
    c = Conversation(user_id=user.id, kb_id=body.kb_id, title=body.title)
    db.add(c)
    await db.flush()
    return c


async def _get_conv(
    db: AsyncSession, cid: int, user_id: int
) -> Conversation:
    r = await db.execute(
        select(Conversation).where(Conversation.id == cid, Conversation.user_id == user_id)
    )
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return c


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Message]:
    await _get_conv(db, conversation_id, user.id)
    r = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
    )
    return [m for m in r.scalars().all() if m.role in ("user", "assistant")]


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _get_conv(db, conversation_id, user.id)
    await db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await db.execute(
        delete(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )
    return {"status": "ok"}


@router.post("/{conversation_id}/messages")
async def post_message(
    request: Request,
    conversation_id: int,
    body: MessageBody,
    user: User = Depends(require_chat_ready),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    request_id = getattr(request.state, "request_id", "")
    conv = await _get_conv(db, conversation_id, user.id)
    if body.chat_model_id is not None:
        if not await resolve_chat_model(db, user.id, body.chat_model_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="chat_model_id 无效、未启用或不属于当前用户",
            )
    um = Message(
        conversation_id=conv.id,
        role="user",
        content=body.content,
        citations_json=None,
    )
    db.add(um)
    await db.flush()

    async def gen():
        # 立即写出首字节，避免客户端/反向代理在首包前长时间显示「无响应」
        yield ": sse\n\n"
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "meta",
                    "request_id": request_id,
                    "conversation_id": conv.id,
                    "chat_model_id": body.chat_model_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
        async for chunk in stream_chat_reply(
            db,
            user_id=user.id,
            kb_id=conv.kb_id,
            conversation_id=conv.id,
            user_text=body.content,
            user_message_id=um.id,
            acl_user=user,
            chat_model_id=body.chat_model_id,
            request_id=request_id or None,
        ):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )
