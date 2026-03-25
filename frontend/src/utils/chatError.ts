/** 将后端错误响应体解析为可读字符串 */
export function messageFromHttpBody(text: string): string {
  let msg = text;
  try {
    const j = JSON.parse(text) as {
      detail?: string | { message?: string; code?: string };
    };
    const d = j.detail;
    if (typeof d === "string") msg = d;
    else if (d && typeof d === "object" && "message" in d && d.message)
      msg = String(d.message);
  } catch {
    /* 非 JSON */
  }
  return String(msg).slice(0, 500);
}
