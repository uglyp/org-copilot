"""
通过 HTTP 调用「OpenAI 兼容」接口（`/v1/embeddings`、`/v1/chat/completions`）。

- 使用 `httpx.AsyncClient`：与 FastAPI 同为异步栈，适合高并发。
- `stream=True` 时按行解析 SSE 风格响应（`data: {...}`），累加 `delta.content`。
- 本地向量开启时走 `local_embed`，不访问远程 embedding API。
"""

import json
from typing import Any, AsyncIterator

import httpx

from app.core.config import get_settings
from app.services.local_embed import embed_texts_local
from app.services.model_resolver import ResolvedOpenAICompat


def _openai_v1_base(api_base: str) -> str:
    """统一为 `.../v1`，避免用户在模型设置里填 `http://host:11434/v1` 时再拼出 `/v1/v1/...` 导致 404。"""
    b = (api_base or "").strip().rstrip("/")
    if not b:
        raise ValueError("api_base 为空")
    if b.endswith("/v1"):
        return b
    return f"{b}/v1"


async def embed_texts(
    cfg: ResolvedOpenAICompat | None, texts: list[str]
) -> list[list[float]]:
    """本地向量（USE_LOCAL_EMBEDDING=true）时忽略 cfg；否则必须提供 OpenAI 兼容 embedding 配置。"""
    settings = get_settings()
    if settings.use_local_embedding:
        return await embed_texts_local(texts)
    if not cfg:
        raise ValueError("embedding 未配置：请设置 USE_LOCAL_EMBEDDING=true 或配置默认向量模型")
    url = f"{_openai_v1_base(cfg.api_base)}/embeddings"
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    if cfg.extra_headers:
        headers.update(cfg.extra_headers)
    payload = {"model": cfg.model_id, "input": texts}
    # connect 超时避免错误 base 时长时间挂死；read 给足时间给大 batch
    t = httpx.Timeout(120.0, connect=30.0)
    async with httpx.AsyncClient(timeout=t) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    return [d["embedding"] for d in data["data"]]


async def chat_completion_stream(
    cfg: ResolvedOpenAICompat,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    """流式：逐段 yield 文本 token（字符串）。"""
    url = f"{_openai_v1_base(cfg.api_base)}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    if cfg.extra_headers:
        headers.update(cfg.extra_headers)
    payload: dict[str, Any] = {
        "model": cfg.model_id,
        "messages": messages,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0].get("delta") or {}
                        # OpenAI 兼容；推理模型可能只有 reasoning_content，无 content
                        piece = delta.get("content") or ""
                        if not piece and delta.get("reasoning_content"):
                            piece = str(delta["reasoning_content"])
                        if piece:
                            yield piece
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


async def probe_chat(cfg: ResolvedOpenAICompat) -> None:
    """模型设置页「探测」：发极小请求验证 base_url 与 key 是否可用。"""
    url = f"{_openai_v1_base(cfg.api_base)}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    if cfg.extra_headers:
        headers.update(cfg.extra_headers)
    payload: dict[str, Any] = {
        "model": cfg.model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 8,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()


async def probe_embedding(cfg: ResolvedOpenAICompat) -> None:
    """同上，针对 embedding 端点。"""
    url = f"{_openai_v1_base(cfg.api_base)}/embeddings"
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    if cfg.extra_headers:
        headers.update(cfg.extra_headers)
    payload = {"model": cfg.model_id, "input": "ping"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
