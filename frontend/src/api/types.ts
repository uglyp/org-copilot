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
  provider_kind: "local" | "remote";
  subtitle: string;
}

/** GET/PATCH /auth/me 与登录后用户信息 */
export interface MeUser {
  id: number;
  username: string;
  branch: string;
  role: string;
  security_level: number;
  departments: string[];
  org_id: string | null;
}

export interface MePatchResponse extends MeUser {
  access_token: string;
  token_type: string;
}

export interface KnowledgeBaseOut {
  id: number;
  /** 知识库属主用户 ID，用于判断是否可编辑文档元数据等 */
  user_id: number;
  name: string;
  description: string | null;
  org_id: string | null;
  is_org_shared: boolean;
}

export interface DocumentOut {
  id: number;
  filename: string;
  /** text | image */
  modality: string;
  status: string;
  error_message: string | null;
  branch: string;
  security_level: number;
  department: string | null;
  /** 上传者；与知识库 user_id 共同决定可否 PATCH 元数据 */
  creator_user_id: number | null;
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
