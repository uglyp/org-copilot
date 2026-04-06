#!/usr/bin/env python3
"""
验证 RAG 对话「整包 prompt」相对本地模型上下文是否可能溢出。

在 backend 目录执行：
  uv run python scripts/verify_rag_context_budget.py
  uv run python scripts/verify_rag_context_budget.py --top-k 6
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from app.core.config import get_settings
from app.services.usage_tokens import estimate_chat_prompt_tokens


def build_synthetic_messages(
    top_k: int, chunk_chars: int, hist_turns: int
) -> list[dict[str, str]]:
    """与 rag_chat 结构一致：双 system + 历史 + 当前 user。"""
    system1 = (
        "你是知识库问答助手。请严格依据下方「知识库片段」作答。\n"
        "若片段中含 Markdown 表格、列表（例如「推荐技术栈」中的前端/后端/语言），请从中归纳事实后再回答。\n"
        "仅当片段中确实没有与问题相关的信息时，再明确说明「知识库片段中未找到」，不要编造。\n"
        "不要编造片段中不存在的事实。"
    )
    chunk_body = "测" * chunk_chars
    parts = [
        f"[片段 id={i} 来源文件=demo.pdf] {chunk_body}" for i in range(top_k)
    ]
    system2 = "知识库片段：\n" + "\n\n".join(parts)
    msgs: list[dict[str, str]] = [
        {"role": "system", "content": system1},
        {"role": "system", "content": system2},
    ]
    for t in range(hist_turns):
        msgs.append(
            {"role": "user", "content": f"历史问题{t}约二十字内容占位占位占位"}
        )
        msgs.append(
            {
                "role": "assistant",
                "content": f"历史回答{t}约四十汉字模拟多轮对话体积。" * 2,
            }
        )
    msgs.append(
        {"role": "user", "content": "当前用户问题：请根据上文知识库片段回答具体问题。"}
    )
    return msgs


def _ollama_get(url: str, timeout: float = 3.0) -> dict | None:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None


def _ollama_show(base: str, model_name: str) -> dict | None:
    url = f"{base.rstrip('/')}/api/show"
    try:
        body = json.dumps({"name": model_name}).encode()
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None


def _find_context_keys(model_info: dict) -> dict[str, int]:
    """从 Ollama model_info 里找与 context 长度相关的整数字段。"""
    out: dict[str, int] = {}
    for k, v in model_info.items():
        lk = str(k).lower()
        if not isinstance(v, int):
            continue
        if "context" in lk or lk.endswith(".length") and "rope" not in lk:
            if v > 0:
                out[str(k)] = v
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG prompt 体量 vs 本地上下文")
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="覆盖环境变量 RAG_TOP_K（默认读配置）",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=800,
        help="单块最大字符数，与 text_chunking.chunk_text 默认 chunk_size 一致",
    )
    parser.add_argument(
        "--history-turns",
        type=int,
        default=10,
        help="与 rag_chat._load_history limit 一致",
    )
    parser.add_argument(
        "--ollama",
        default="http://127.0.0.1:11434",
        help="Ollama 根地址，用于读取 /api/tags 与 /api/show",
    )
    args = parser.parse_args()

    settings = get_settings()
    top_k = args.top_k if args.top_k is not None else settings.rag_top_k
    msgs = build_synthetic_messages(top_k, args.chunk_chars, args.history_turns)
    est = estimate_chat_prompt_tokens(msgs)
    blob = json.dumps(msgs, ensure_ascii=False)
    content_chars = sum(len(m.get("content", "")) for m in msgs)

    print("=== OrgCopilot RAG 上下文粗测 ===\n")
    print(
        f"假设：top_k={top_k}，每块满 {args.chunk_chars} 字（中文），"
        f"历史 {args.history_turns} 轮 user+assistant，含当前问题。"
    )
    print(f"整包 messages 序列化 JSON 字符数: {len(blob)}")
    print(f"各条 content 字符合计: {content_chars}")
    print(
        f"项目内 estimate_chat_prompt_tokens（≈ ceil(JSON字符/2)，偏 CJK）: {est}"
    )
    print()
    print("解读：")
    print(
        "  - 若 Ollama 的 num_ctx 小于下表「粗算 prompt」，则输入可能被截断，"
        "本地易表现为「答不出」或乱答。"
    )
    print("  - 在线 API 通常提供更大上下文（如 8k～128k），故同样检索结果仍可答。")
    print()
    for threshold in (2048, 4096, 8192):
        flag = "可能截断" if est > threshold else "通常可放下（仅指 prompt）"
        print(f"  常见 num_ctx={threshold}: 粗算 {est} → {flag}")
    print()

    tags = _ollama_get(f"{args.ollama.rstrip('/')}/api/tags")
    if not tags:
        print(f"未连上 Ollama（{args.ollama}），跳过模型参数探测。")
        return 0

    names = [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
    print(f"Ollama（{args.ollama}）可见模型 {len(names)} 个；抽样读取 /api/show：\n")
    for name in names[:5]:
        show = _ollama_show(args.ollama, name)
        if not show:
            print(f"  - {name!r}: show 失败")
            continue
        mi = show.get("model_info")
        if not isinstance(mi, dict):
            print(f"  - {name!r}: 无 model_info")
            continue
        ctx_map = _find_context_keys(mi)
        details = show.get("details") or {}
        fam = details.get("family") or details.get("parameter_size") or ""
        # 常见：llama.context_length、gemma2.context_length 等
        if ctx_map:
            best = max(ctx_map.values())
            print(f"  - {name!r} ({fam}): model_info 中上下文相关整数 → {ctx_map}")
            print(f"    → 最大可见值 {best}（与 Ollama num_ctx 常一致或同源）")
            if est > best:
                print(
                    f"    ⚠ 粗算 prompt≈{est} > ctx {best}，**很可能被截断**，本地易答不出或乱答。"
                )
            elif est > int(best * 0.85):
                print(
                    f"    △ 粗算 prompt≈{est} 已占 ctx {best} 的 {100 * est // best}%，"
                    "留出生成空间后仍可能偏紧。"
                )
            else:
                print(
                    f"    ✓ 粗算 prompt≈{est} 明显小于 ctx {best}，**单纯上下文截断概率较低**；"
                    "若仍答不好，更可能是小模型遵循指令/读 OCR 噪声能力弱。"
                )
        else:
            print(f"  - {name!r} ({fam}): 未从 model_info 解析到 context 长度键")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
