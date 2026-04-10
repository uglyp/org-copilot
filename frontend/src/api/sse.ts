// 对话流：解析后端 text/event-stream 的 data 行（与 rag_chat._sse 格式对应）
export interface SseToken {
  type: "token";
  content: string;
}

export interface SseDone {
  type: "done";
  citations: Array<Record<string, unknown>>;
  full_text: string;
  message_id: number;
}

export interface SseError {
  type: "error";
  code?: string;
}

/** 后端阶段提示：embedding → searching → generating */
export interface SseStatus {
  type: "status";
  phase: string;
}

export type SsePayload = SseToken | SseDone | SseError | SseStatus;
export interface SseOpenMeta {
  requestId: string;
}

export async function postMessageStream(
  url: string,
  token: string,
  body: { content: string; chat_model_id?: number },
  onEvent: (ev: SsePayload) => void,
  onOpen?: (meta: SseOpenMeta) => void
): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  onOpen?.({ requestId: res.headers.get("X-Request-ID") ?? "" });

  const reader = res.body?.getReader();
  if (!reader) throw new Error("无响应流");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const line = block.trim();
      if (!line.startsWith("data:")) continue;
      const jsonStr = line.slice(5).trim();
      if (!jsonStr) continue;
      try {
        const data = JSON.parse(jsonStr) as SsePayload;
        onEvent(data);
      } catch {
        // ignore parse errors for partial chunks
      }
    }
  }
}
