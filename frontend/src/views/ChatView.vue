<script setup lang="ts">
/**
 * 对话页：Sender variant=updown（上输入、下工具栏），避免 EditorSender 富文本光标/占位异常
 * @see https://element-plus-x.com/components/Sender
 */
import {
  computed,
  markRaw,
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { Delete } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox, ElScrollbar } from "element-plus";
import {
  Conversations,
  Sender,
  ThoughtChain,
  Typewriter,
  XMarkdown,
} from "vue-element-plus-x";
import { getApiBaseForFetch, http } from "@/api/http";
import { postMessageStream } from "@/api/sse";
import type { SseDone, SsePayload } from "@/api/sse";
import type {
  ChatModelOptionOut,
  ConversationOut,
  KnowledgeBaseOut,
  MessageOut,
} from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { messageFromHttpBody } from "@/utils/chatError";

type ChatMsg = { role: "user" | "assistant"; content: string };

type StreamPhase = "embedding" | "searching" | "generating";
type DiagnosticMeta = {
  requestId: string;
  conversationId: number | null;
  chatModelId: number | null;
  timestamp: string;
};

const CHAT_MODEL_LS = "org_copilot_chat_model_id";
/** 旧版 localStorage 键，启动时迁移至 CHAT_MODEL_LS */
const LEGACY_CHAT_MODEL_LS = "kb_copilot_chat_model_id";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const kbs = ref<KnowledgeBaseOut[]>([]);
const convs = ref<ConversationOut[]>([]);
const activeConvId = ref<number | null>(null);
const newKbId = ref<number | null>(null);

const activeConv = ref<ConversationOut | null>(null);
const messages = ref<ChatMsg[]>([]);
const inputText = ref("");
const sending = ref(false);
const streamPhase = ref<StreamPhase | null>(null);
const latestRequestId = ref("");
const latestDiagnostic = ref<DiagnosticMeta>({
  requestId: "",
  conversationId: null,
  chatModelId: null,
  timestamp: "",
});

const selectedChatModelKey = ref("");
const chatModels = ref<ChatModelOptionOut[]>([]);

const senderRef = ref<{ clear: () => void } | null>(null);

const chatScrollbarRef = ref<InstanceType<typeof ElScrollbar> | null>(null);

let chatScrollResizeObserver: ResizeObserver | null = null;

function disconnectChatScrollObserver() {
  chatScrollResizeObserver?.disconnect();
  chatScrollResizeObserver = null;
}

/** 对话区滚到底（流式/Markdown 渲染后高度异步变化，必要时多帧再滚一次） */
function scrollChatToBottom() {
  const run = () => {
    const bar = chatScrollbarRef.value;
    const wrap = bar?.wrapRef;
    if (!wrap) return;
    const h = wrap.scrollHeight;
    bar.setScrollTop(h);
  };
  void nextTick(() => {
    requestAnimationFrame(() => {
      run();
      requestAnimationFrame(run);
    });
  });
}

function attachChatScrollObserver() {
  disconnectChatScrollObserver();
  const wrap = chatScrollbarRef.value?.wrapRef;
  const inner = wrap?.querySelector(".el-scrollbar__view") as HTMLElement | null;
  if (!inner) return;
  chatScrollResizeObserver = new ResizeObserver(() => {
    if (sending.value) scrollChatToBottom();
  });
  chatScrollResizeObserver.observe(inner);
}

const conversationItems = computed(() =>
  convs.value.map((c) => ({
    id: c.id,
    label: (c.title && c.title.trim()) || `会话 #${c.id}`,
    kb_id: c.kb_id,
  }))
);

const conversationMenu = [
  {
    label: "删除",
    key: "delete",
    icon: markRaw(Delete),
    command: "delete",
    menuItemHoverStyle: { color: "red", backgroundColor: "rgba(255, 0, 0, 0.08)" },
  },
];

/** Conversations 内联样式（覆盖库默认 280px 宽、height:0） */
const conversationWrapStyle = {
  width: "100%",
  height: "100%",
  minHeight: "0",
  padding: "4px 0",
  backgroundColor: "transparent",
  borderRadius: "0",
};
const conversationItemStyle = {
  borderRadius: "10px",
  marginBottom: "4px",
  padding: "10px 12px",
};
const conversationHoverStyle = {
  backgroundColor: "hsl(var(--muted) / 0.65)",
};
const conversationActiveStyle = {
  backgroundColor: "hsl(var(--primary) / 0.12)",
  color: "hsl(var(--foreground))",
};

const thoughtChainItems = computed(() => {
  if (!sending.value || !streamPhase.value) return [];
  const phases: { id: string; title: string; line: string; key: StreamPhase }[] =
    [
      {
        id: "p1",
        key: "embedding",
        title: "问题向量化",
        line: "Embedding 用户问题",
      },
      {
        id: "p2",
        key: "searching",
        title: "知识库检索",
        line: "在向量库中召回 Top-K 片段",
      },
      {
        id: "p3",
        key: "generating",
        title: "模型生成",
        line: "拼接上下文并流式输出",
      },
    ];
  const order: StreamPhase[] = ["embedding", "searching", "generating"];
  const cur = order.indexOf(streamPhase.value);
  return phases.slice(0, cur + 1).map((p, idx) => ({
    id: p.id,
    title: p.title,
    thinkTitle: p.line,
    thinkContent: "",
    isCanExpand: false,
    isDefaultExpand: false,
    status: (idx < cur ? "success" : "loading") as "loading" | "success" | "error",
  }));
});

watch(selectedChatModelKey, (v) => {
  if (v === "") localStorage.removeItem(CHAT_MODEL_LS);
  else localStorage.setItem(CHAT_MODEL_LS, v);
});

function isLastAssistantIndex(i: number) {
  return i === messages.value.length - 1 && messages.value[i]?.role === "assistant";
}

/** 助手正文统一用 XMarkdown，与流式阶段一致（含表格边框等）；勿在结束后改用 Typewriter，否则表格等样式会丢失 */
function useXMarkdownForAssistant(i: number) {
  const m = messages.value[i];
  return m?.role === "assistant" && m.content.length > 0;
}

/** 展示思考链：有阶段且尚未输出正文 token，避免与下方 Markdown 重复占位 */
function showThoughtChainPanel(i: number) {
  return (
    sending.value &&
    isLastAssistantIndex(i) &&
    !!streamPhase.value &&
    thoughtChainItems.value.length > 0 &&
    !useXMarkdownForAssistant(i)
  );
}

watch(
  () => messages.value.map((m) => m.content).join("\0"),
  () => {
    if (sending.value) scrollChatToBottom();
  },
  { flush: "post" }
);

watch(streamPhase, () => {
  if (sending.value) scrollChatToBottom();
});

watch(
  () => messages.value.length,
  () => {
    scrollChatToBottom();
  },
  { flush: "post" }
);

watch(sending, (s) => {
  if (s) {
    void nextTick(() => {
      attachChatScrollObserver();
      scrollChatToBottom();
    });
  } else {
    disconnectChatScrollObserver();
  }
});

async function loadKbs() {
  const { data } = await http.get<KnowledgeBaseOut[]>("/knowledge-bases");
  kbs.value = data;
  if (data.length && newKbId.value == null) {
    newKbId.value = data[0].id;
  }
}

async function loadConvs() {
  const { data } = await http.get<ConversationOut[]>("/conversations");
  convs.value = data;
}

async function loadChatModels() {
  try {
    const legacy = localStorage.getItem(LEGACY_CHAT_MODEL_LS);
    if (legacy && !localStorage.getItem(CHAT_MODEL_LS)) {
      localStorage.setItem(CHAT_MODEL_LS, legacy);
      localStorage.removeItem(LEGACY_CHAT_MODEL_LS);
    }
    const { data } = await http.get<ChatModelOptionOut[]>("/me/chat-models");
    chatModels.value = data;
    const saved = localStorage.getItem(CHAT_MODEL_LS);
    if (saved && data.some((m) => m.id === Number(saved))) {
      selectedChatModelKey.value = saved;
    } else {
      const def = data.find((m) => m.is_default);
      const fallback = def ?? data[0];
      selectedChatModelKey.value = fallback ? String(fallback.id) : "";
    }
  } catch {
    chatModels.value = [];
  }
}

function clearChat() {
  messages.value = [];
}

function messageToChatRow(m: MessageOut): ChatMsg {
  const role = m.role === "user" ? "user" : "assistant";
  return { role, content: m.content };
}

async function loadMessages(convId: number) {
  try {
    const { data } = await http.get<MessageOut[]>(
      `/conversations/${convId}/messages`
    );
    messages.value = data.map(messageToChatRow);
  } catch (e) {
    const raw = e instanceof Error ? e.message : String(e);
    ElMessage.error(`加载历史失败：${messageFromHttpBody(raw)}`);
    clearChat();
  }
}

async function createConv() {
  if (!newKbId.value) {
    ElMessage.warning("请选择知识库");
    return;
  }
  const { data } = await http.post<ConversationOut>("/conversations", {
    kb_id: newKbId.value,
    title: null,
  });
  convs.value.unshift(data);
  await router.replace({
    name: "chat",
    params: { conversationId: String(data.id) },
  });
}

async function selectConv(id: number) {
  activeConvId.value = id;
  activeConv.value = convs.value.find((c) => c.id === id) ?? null;
  await loadMessages(id);
}

async function onConversationChange(item: Record<string, unknown>) {
  const id = item.id as number;
  await router.push({ name: "chat", params: { conversationId: String(id) } });
}

async function onConversationMenuCommand(
  command: string | number | object,
  item: Record<string, unknown>
) {
  if (command === "delete" && typeof item.id === "number") {
    await deleteConv(item.id);
  }
}

async function deleteConv(id: number) {
  try {
    await ElMessageBox.confirm(`确定删除会话 #${id}？历史消息将一并删除。`, "删除会话", {
      type: "warning",
    });
  } catch {
    return;
  }
  try {
    await http.delete(`/conversations/${id}`);
    convs.value = convs.value.filter((c) => c.id !== id);
    ElMessage.success("已删除");
    if (activeConvId.value === id) {
      if (convs.value.length) {
        await router.replace({
          name: "chat",
          params: { conversationId: String(convs.value[0].id) },
        });
      } else {
        await router.replace({ name: "chat" });
        activeConvId.value = null;
        activeConv.value = null;
        clearChat();
      }
    }
  } catch (e) {
    const raw = e instanceof Error ? e.message : String(e);
    ElMessage.error(`删除失败：${messageFromHttpBody(raw)}`);
  }
}

function parseRouteConversationId(): number | null {
  const raw = route.params.conversationId;
  const str = Array.isArray(raw) ? raw[0] : raw;
  if (!str) return null;
  const id = Number(str);
  return Number.isInteger(id) && id > 0 ? id : null;
}

async function syncConversationFromRoute() {
  if (!convs.value.length) {
    activeConvId.value = null;
    activeConv.value = null;
    clearChat();
    return;
  }

  const routeId = parseRouteConversationId();
  if (routeId == null) {
    const fallbackId = activeConvId.value ?? convs.value[0].id;
    await router.replace({
      name: "chat",
      params: { conversationId: String(fallbackId) },
    });
    return;
  }

  const exists = convs.value.some((c) => c.id === routeId);
  if (!exists) {
    ElMessage.warning(`会话 #${routeId} 不存在或已删除，已切换到可用会话`);
    await router.replace({
      name: "chat",
      params: { conversationId: String(convs.value[0].id) },
    });
    return;
  }
  if (activeConvId.value === routeId) return;
  await selectConv(routeId);
}

function patchComposerTextarea() {
  void nextTick(() => {
    const root = document.querySelector(".chat-sender-updown");
    const ta = root?.querySelector("textarea");
    if (!ta) return;
    ta.setAttribute("spellcheck", "false");
    ta.setAttribute("autocomplete", "off");
    ta.setAttribute("data-gramm", "false");
    ta.setAttribute("data-gramm_editor", "false");
    ta.setAttribute("data-enable-grammarly", "false");
  });
}

async function sendMessage(text?: string) {
  const raw = (text ?? inputText.value).trim();
  const convId = activeConvId.value;
  const token = auth.token;
  if (!raw || sending.value) return;
  if (!convId) {
    ElMessage.warning("请先选择或创建会话");
    return;
  }
  if (!token) {
    ElMessage.warning("未登录，请重新登录");
    return;
  }

  inputText.value = "";
  senderRef.value?.clear();
  streamPhase.value = null;

  messages.value.push({ role: "user", content: raw });
  messages.value.push({ role: "assistant", content: "" });
  const assistantIdx = messages.value.length - 1;
  latestDiagnostic.value = {
    requestId: "",
    conversationId: convId,
    chatModelId: null,
    timestamp: "",
  };

  const url = `${getApiBaseForFetch()}/conversations/${convId}/messages`;
  sending.value = true;

  let acc = "";
  try {
    const streamBody: { content: string; chat_model_id?: number } = {
      content: raw,
    };
    const mid = Number(selectedChatModelKey.value);
    const def = chatModels.value.find((m) => m.is_default);
    if (selectedChatModelKey.value !== "" && !Number.isNaN(mid)) {
      if (!def || mid !== def.id) {
        streamBody.chat_model_id = mid;
      }
    }
    await postMessageStream(
      url,
      token,
      streamBody,
      (ev: SsePayload) => {
        const last = messages.value[assistantIdx];
        if (!last || last.role !== "assistant") return;

        if (ev.type === "token" && ev.content) {
          streamPhase.value = "generating";
          acc += ev.content;
          last.content = acc;
        } else if (ev.type === "status") {
          const phase = (ev as { phase?: string }).phase;
          if (phase === "embedding") streamPhase.value = "embedding";
          else if (phase === "searching") streamPhase.value = "searching";
          else if (phase === "generating") streamPhase.value = "generating";
          /* 进度由 ThoughtChain 展示，勿再写入 assistant 文案，避免与占位区重复 */
          if (!acc) last.content = "";
        } else if (ev.type === "done") {
          const done = ev as SseDone;
          acc = done.full_text || acc;
          last.content = acc;
          streamPhase.value = "generating";
        } else if (ev.type === "error") {
          last.content = `错误：${(ev as { code?: string }).code ?? "对话出错"}`;
        } else if (ev.type === "meta") {
          latestDiagnostic.value = {
            requestId: ev.request_id ?? latestRequestId.value,
            conversationId: ev.conversation_id ?? convId,
            chatModelId: ev.chat_model_id ?? null,
            timestamp: ev.timestamp ?? "",
          };
          latestRequestId.value = ev.request_id ?? latestRequestId.value;
        }
      },
      ({ requestId }) => {
        latestRequestId.value = requestId;
        latestDiagnostic.value = {
          ...latestDiagnostic.value,
          requestId,
          timestamp: latestDiagnostic.value.timestamp || new Date().toISOString(),
        };
      }
    );
  } catch (e) {
    const last = messages.value[assistantIdx];
    if (last?.role === "assistant") {
      const errRaw = e instanceof Error ? e.message : String(e);
      last.content = `请求失败：${messageFromHttpBody(errRaw)}`;
    }
  } finally {
    sending.value = false;
    streamPhase.value = null;
  }
}

async function copyDiagnosticInfo() {
  if (!latestDiagnostic.value.requestId) {
    ElMessage.warning("当前会话暂无可复制的诊断信息");
    return;
  }
  const payload = {
    request_id: latestDiagnostic.value.requestId,
    conversation_id: latestDiagnostic.value.conversationId,
    chat_model_id: latestDiagnostic.value.chatModelId,
    timestamp: latestDiagnostic.value.timestamp || new Date().toISOString(),
  };
  try {
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    ElMessage.success("诊断信息已复制");
  } catch {
    ElMessage.error("复制失败，请检查浏览器剪贴板权限");
  }
}

function onSenderSubmit(internalValue: string) {
  void sendMessage(internalValue);
}

onMounted(async () => {
  await loadKbs();
  await loadConvs();
  await loadChatModels();
  patchComposerTextarea();
  await syncConversationFromRoute();
});

watch(
  () => route.params.conversationId,
  () => {
    void syncConversationFromRoute();
  }
);

watch([chatModels, activeConvId], () => patchComposerTextarea(), { flush: "post" });

onUnmounted(() => {
  disconnectChatScrollObserver();
});
</script>

<template>
  <div
    class="kb-page-shell chat-page flex h-[calc(100dvh-56px-56px)] min-h-0 flex-col overflow-hidden"
  >
    <p class="kb-page-title shrink-0">智能对话</p>
    <div
      class="chat-layout grid min-h-0 flex-1 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] gap-5 lg:grid-cols-12 lg:grid-rows-[minmax(0,1fr)] lg:items-stretch"
    >
      <!-- 侧栏：会话列表 + 知识库 -->
      <aside
        class="chat-aside flex min-h-0 flex-col rounded-xl border border-border bg-card shadow-sm lg:col-span-4"
      >
        <div
          class="border-b border-border px-4 py-3 text-sm font-semibold text-foreground"
        >
          会话与知识库
        </div>
        <div class="flex min-h-0 flex-1 flex-col gap-3 p-4">
          <el-select
            v-model="newKbId"
            placeholder="选择知识库"
            size="large"
            class="w-full"
          >
            <el-option
              v-for="k in kbs"
              :key="k.id"
              :label="k.name"
              :value="k.id"
            />
          </el-select>
          <el-button
            type="primary"
            class="w-full !rounded-lg"
            round
            @click="createConv"
          >
            新会话
          </el-button>

          <div class="chat-conversations-panel min-h-0 flex-1">
            <Conversations
              v-if="convs.length"
              :active="activeConvId ?? undefined"
              :items="conversationItems"
              row-key="id"
              label-key="label"
              :show-built-in-menu="true"
              :menu="conversationMenu"
              :show-tooltip="true"
              tooltip-placement="top"
              :label-max-width="220"
              :items-style="conversationItemStyle"
              :items-hover-style="conversationHoverStyle"
              :items-active-style="conversationActiveStyle"
              :style="conversationWrapStyle"
              @change="onConversationChange"
              @menu-command="onConversationMenuCommand"
            />
            <div
              v-else
              class="flex min-h-[160px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 px-2 py-6 text-center text-xs text-muted-foreground"
            >
              暂无会话，请先新建
            </div>
          </div>
        </div>
      </aside>

      <!-- 主区 -->
      <section
        class="flex min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-sm lg:col-span-8"
      >
        <div class="border-b border-border px-4 py-3">
          <div class="flex items-center justify-between gap-2">
            <div v-if="activeConv" class="text-sm font-medium text-foreground">
              会话 <span class="font-semibold">#{{ activeConv.id }}</span>
              <span class="ml-2 text-muted-foreground"
                >· 知识库 {{ activeConv.kb_id }}</span
              >
            </div>
            <div v-else class="text-sm text-muted-foreground">
              请选择或创建会话
            </div>
            <el-button
              size="small"
              text
              :disabled="!latestDiagnostic.requestId"
              @click="copyDiagnosticInfo"
            >
              复制诊断信息
            </el-button>
          </div>
        </div>

        <div class="flex min-h-0 flex-1 flex-col bg-muted/30">
          <div
            v-if="!messages.length"
            class="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-10"
          >
            <p class="max-w-md text-center text-sm leading-relaxed text-muted-foreground">
              你好，我是
              <strong class="text-foreground">知识库助手</strong
              >。选择知识库并新建会话后，即可基于知识库内容提问。
            </p>
            <Typewriter
              class="max-w-md text-center text-xs text-muted-foreground"
              content="支持 Markdown、代码块与流式回答。"
              :is-markdown="true"
              :typing="false"
            />
          </div>

          <div
            v-else
            class="flex min-h-0 flex-1 flex-col overflow-hidden"
          >
            <el-scrollbar
              ref="chatScrollbarRef"
              class="chat-msg-scroll min-h-0 flex-1 px-3 py-4 sm:px-5"
            >
              <div
                v-for="(m, i) in messages"
                :key="i"
                class="mb-4"
              >
                <div
                  v-if="m.role === 'user'"
                  class="flex justify-end"
                >
                  <div
                    class="max-w-[min(100%,42rem)] rounded-2xl border border-primary/20 bg-primary/10 px-4 py-2.5 text-sm text-foreground shadow-sm"
                  >
                    {{ m.content }}
                  </div>
                </div>

                <div
                  v-else
                  class="max-w-[min(100%,48rem)] space-y-3"
                >
                  <div
                    v-if="showThoughtChainPanel(i)"
                    class="chat-thought-panel"
                  >
                    <p class="chat-thought-panel-title text-xs font-medium text-muted-foreground">
                      处理进度
                    </p>
                    <ThoughtChain
                      :thinking-items="thoughtChainItems"
                      max-width="100%"
                    />
                  </div>

                  <div
                    v-if="useXMarkdownForAssistant(i)"
                    class="elx-md-stream rounded-xl border border-border bg-background px-3 py-2 shadow-sm"
                  >
                    <XMarkdown :markdown="m.content" />
                  </div>

                  <div
                    v-else-if="m.role === 'assistant' && !showThoughtChainPanel(i)"
                    class="rounded-xl border border-dashed border-border/80 bg-background/80 px-3 py-2 text-sm text-muted-foreground"
                  >
                    {{ m.content || "…" }}
                  </div>
                </div>
              </div>
            </el-scrollbar>
          </div>

          <div class="composer-bar border-t border-border bg-muted/30 px-3 py-3 sm:px-4">
            <p
              v-if="!chatModels.length"
              class="mb-2 px-1 text-xs text-muted-foreground"
            >
              未加载到可用对话模型，请先在「模型设置」中配置。
            </p>
            <div
              class="composer-sender-shell overflow-hidden rounded-2xl border border-border bg-card shadow-composer"
            >
              <Sender
                ref="senderRef"
                v-model="inputText"
                variant="updown"
                :show-updown="true"
                :submit-type="'enter'"
                :loading="sending"
                :disabled="!activeConvId || sending"
                :allow-speech="false"
                :clearable="false"
                placeholder="输入问题…（Enter 发送，Shift+Enter 换行）"
                :auto-size="{ minRows: 2, maxRows: 10 }"
                class="chat-sender-updown"
                @submit="onSenderSubmit"
              >
                <template v-if="chatModels.length" #prefix>
                  <div class="chat-model-prefix flex min-w-0 flex-1 items-center gap-2">
                    <span class="shrink-0 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
                      >模型</span
                    >
                    <el-select
                      v-model="selectedChatModelKey"
                      size="small"
                      class="composer-model-select model-select-pill min-w-0 flex-1"
                      filterable
                      :teleported="true"
                      placeholder="选择模型"
                    >
                      <el-option
                        v-for="m in chatModels"
                        :key="m.id"
                        :value="String(m.id)"
                        :label="m.display_name"
                      >
                        <div class="model-option-stack py-0.5">
                          <div class="text-sm font-medium leading-snug text-foreground">
                            {{ m.display_name }}
                          </div>
                          <div class="text-xs leading-snug text-muted-foreground">
                            {{ m.subtitle || "—" }}
                          </div>
                        </div>
                      </el-option>
                    </el-select>
                  </div>
                </template>
              </Sender>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.chat-aside {
  min-height: 0;
}

/* 会话列表：覆盖组件库默认 width:280px、height:0，撑满侧栏 */
.chat-conversations-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-radius: 0.5rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--muted) / 0.35);
  overflow: hidden;
}

.chat-conversations-panel :deep(.conversations-container) {
  width: 100% !important;
  max-width: 100% !important;
  min-height: 0 !important;
  flex: 1 1 auto;
  height: 100% !important;
  display: flex;
  flex-direction: column;
  padding: 8px 6px !important;
  box-sizing: border-box;
}

.chat-conversations-panel :deep(.conversations-scroll-wrapper) {
  flex: 1 1 auto;
  min-height: 0;
}

.chat-conversations-panel :deep(.conversations-list) {
  min-height: 0;
}

.chat-conversations-panel :deep(.conversation-item) {
  border-radius: 10px;
}

.chat-msg-scroll {
  min-height: 0;
}

.composer-bar {
  flex-shrink: 0;
}

/* Sender 垂直变体：原生 textarea，光标/占位符行为正常 */
.composer-sender-shell :deep(.el-sender-wrap) {
  border: none;
  border-radius: inherit;
  background: transparent;
  box-shadow: none;
}

.chat-sender-updown :deep(.el-sender) {
  border: none;
  border-radius: inherit;
  background: transparent;
  box-shadow: none;
}

.chat-sender-updown :deep(.el-sender-content.content-variant-updown) {
  flex-direction: column;
  gap: 0;
  border-radius: inherit;
}

.chat-sender-updown :deep(.el-sender-input) {
  width: 100%;
}

.chat-sender-updown :deep(.el-sender-input .el-textarea__inner) {
  min-height: 5.5rem;
  padding: 0.875rem 1rem 0.75rem;
  font-size: 0.9375rem;
  line-height: 1.55;
  color: hsl(var(--foreground));
  background: hsl(var(--background));
  border: none;
  border-radius: 0;
  box-shadow: none;
  resize: none;
}

.chat-sender-updown :deep(.el-sender-input .el-textarea__inner:focus) {
  outline: none;
  box-shadow: none;
}

.chat-sender-updown :deep(.el-sender-input .el-textarea__inner::placeholder) {
  color: hsl(var(--muted-foreground));
  opacity: 0.92;
}

.chat-sender-updown :deep(.el-sender-updown-wrap) {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.5rem 0.75rem 0.625rem;
  border-top: 1px solid hsl(var(--border) / 0.75);
  background: hsl(var(--muted) / 0.4);
}

.chat-sender-updown :deep(.el-sender-prefix) {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
}

.chat-sender-updown :deep(.el-sender-action-list) {
  flex-shrink: 0;
}

.chat-sender-updown :deep(.el-send-button .el-button) {
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 9999px;
  background: hsl(var(--primary));
  border: none;
  color: hsl(var(--primary-foreground));
  transition:
    transform 0.15s ease,
    filter 0.15s ease,
    opacity 0.15s ease;
}

.chat-sender-updown :deep(.el-send-button .el-button:not(:disabled):hover) {
  filter: brightness(1.06);
}

.chat-sender-updown :deep(.el-send-button .el-button:disabled) {
  opacity: 0.38;
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
}

.model-select-pill :deep(.el-select__wrapper) {
  min-height: 2.125rem;
  border-radius: 9999px;
  padding-left: 0.75rem;
  padding-right: 0.5rem;
  border: 1px solid hsl(var(--border) / 0.85);
  background: hsl(var(--background));
  box-shadow: 0 1px 2px hsl(var(--foreground) / 0.04);
  font-size: 0.8125rem;
  font-weight: 500;
}

.model-select-pill :deep(.el-select__wrapper:hover),
.model-select-pill :deep(.el-select__wrapper.is-focused) {
  border-color: hsl(var(--primary) / 0.5);
}

.composer-model-select:not(.model-select-pill) :deep(.el-select__wrapper) {
  min-height: 32px;
}

.elx-md-stream :deep(.elx-xmarkdown-container) {
  background: transparent;
}

/* 思考链：与对话气泡统一的卡片与时间轴连线 */
.chat-thought-panel {
  width: 100%;
  border-radius: 0.75rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--muted) / 0.4);
  padding: 0.75rem 1rem 0.875rem;
  box-shadow: 0 1px 2px hsl(var(--foreground) / 0.04);
}

.chat-thought-panel-title {
  margin: 0 0 0.5rem;
  letter-spacing: 0.02em;
}

.chat-thought-panel :deep(.el-thought-chain) {
  width: 100%;
}

.chat-thought-panel :deep(.el-collapse) {
  border: none;
}

.chat-thought-panel :deep(.el-timeline) {
  margin: 0;
  padding: 0.25rem 0 0 0.25rem;
}

.chat-thought-panel :deep(.el-timeline-item) {
  padding-bottom: 14px;
}

.chat-thought-panel :deep(.el-timeline-item:last-child) {
  padding-bottom: 0;
}

.chat-thought-panel :deep(.el-timeline-item__tail) {
  left: 5px;
  border-left-width: 2px;
  border-left-color: hsl(var(--border));
}

.chat-thought-panel :deep(.el-timeline-item__wrapper) {
  padding-left: 1.75rem;
}

.chat-thought-panel :deep(.el-timeline-item__timestamp) {
  font-size: 0.8125rem;
  line-height: 1.35;
}

.chat-thought-panel :deep(.el-timeline-item__content) {
  font-size: 0.75rem;
  line-height: 1.4;
  margin-top: 2px;
}
</style>
