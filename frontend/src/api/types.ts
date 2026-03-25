// 与后端 Pydantic 响应字段对齐的 TS 类型（手写，非 openapi 生成）

export interface LLMModelRow {
  id?: number;
  display_name: string;
  model_id: string;
  purpose: "chat" | "embedding";
  is_default: boolean;
  enabled: boolean;
}

export interface ProviderOut {
  id: number;
  name: string;
  api_base: string;
  provider_type: string;
  models: LLMModelRow[];
}

/** GET /me/chat-models：对话页可选 chat 模型 */
export interface ChatModelOptionOut {
  id: number;
  display_name: string;
  model_id: string;
  provider_id: number;
  provider_name: string;
  is_default: boolean;
}

export interface KnowledgeBaseOut {
  id: number;
  name: string;
  description: string | null;
}

export interface DocumentOut {
  id: number;
  filename: string;
  status: string;
  error_message: string | null;
}

export interface ConversationOut {
  id: number;
  kb_id: number;
  title: string | null;
}

export interface MessageOut {
  id: number;
  role: string;
  content: string;
  citations_json: Array<Record<string, unknown>> | null;
}
