<script setup lang="ts">
// OpenAI 兼容提供商：区分「远程 API」与「本地 Ollama」，chat / embedding 行编辑
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import axios from "axios";
import { http } from "@/api/http";
import { messageFromHttpBody } from "@/utils/chatError";
import type { LLMModelRow, ProviderOut } from "@/api/types";
import { useReadinessStore } from "@/stores/readiness";

const readiness = useReadinessStore();
const list = ref<ProviderOut[]>([]);
const loading = ref(false);

const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
/** 新建时用；编辑时由当前行推导，不在表单内切换类型 */
const providerKind = ref<"remote" | "ollama">("remote");

const form = reactive({
  name: "",
  api_base: "",
  api_key: "",
  provider_type: "openai_compatible",
  models: [] as LLMModelRow[],
});

function isLocalProvider(row: ProviderOut): boolean {
  const n = row.name.trim().toLowerCase();
  if (n === "ollama") return true;
  const b = row.api_base.toLowerCase();
  return (
    b.includes("localhost") ||
    b.includes("127.0.0.1") ||
    b.includes(":11434")
  );
}

function defaultRemoteModels(): LLMModelRow[] {
  return [
    {
      display_name: "Chat",
      model_id: "",
      purpose: "chat",
      is_default: true,
      enabled: true,
    },
    {
      display_name: "Embedding",
      model_id: "",
      purpose: "embedding",
      is_default: true,
      enabled: true,
    },
  ];
}

function defaultOllamaModels(): LLMModelRow[] {
  return [
    {
      display_name: "本地对话",
      model_id: "",
      purpose: "chat",
      is_default: true,
      enabled: true,
    },
  ];
}

async function load() {
  loading.value = true;
  try {
    const { data } = await http.get<ProviderOut[]>("/me/providers");
    list.value = data;
    await readiness.fetchReadiness();
  } finally {
    loading.value = false;
  }
}

function openCreateRemote() {
  editingId.value = null;
  providerKind.value = "remote";
  Object.assign(form, {
    name: "",
    api_base: "",
    api_key: "",
    provider_type: "openai_compatible",
    models: defaultRemoteModels(),
  });
  dialogVisible.value = true;
}

function openCreateOllama() {
  editingId.value = null;
  providerKind.value = "ollama";
  Object.assign(form, {
    name: "Ollama",
    api_base: "http://127.0.0.1:11434",
    api_key: "ollama",
    provider_type: "openai_compatible",
    models: defaultOllamaModels(),
  });
  dialogVisible.value = true;
}

function openEdit(row: ProviderOut) {
  editingId.value = row.id;
  providerKind.value = isLocalProvider(row) ? "ollama" : "remote";
  form.name = row.name;
  form.api_base = row.api_base;
  form.api_key = "";
  form.provider_type = row.provider_type;
  form.models = row.models.map((m) => ({ ...m }));
  dialogVisible.value = true;
}

const dialogTitle = computed(() => {
  if (editingId.value) {
    return providerKind.value === "ollama" ? "编辑本地 Ollama" : "编辑远程提供商";
  }
  return providerKind.value === "ollama" ? "添加本地 Ollama" : "添加远程 API 提供商";
});

const isOllamaFlow = computed(() => providerKind.value === "ollama");

function addChatRow() {
  form.models.push({
    display_name: `对话 ${form.models.filter((m) => m.purpose === "chat").length + 1}`,
    model_id: "",
    purpose: "chat",
    is_default: false,
    enabled: true,
  });
}

function addEmbeddingRow() {
  if (isOllamaFlow.value) return;
  form.models.push({
    display_name: "Embedding",
    model_id: "",
    purpose: "embedding",
    is_default: false,
    enabled: true,
  });
}

function removeModelRow(index: number) {
  form.models.splice(index, 1);
}

function onDefaultToggle(row: LLMModelRow, purpose: "chat" | "embedding", on: boolean) {
  if (!on) return;
  for (const m of form.models) {
    if (m.purpose === purpose) m.is_default = m === row;
  }
}

function validateModels(): boolean {
  const chats = form.models.filter((m) => m.purpose === "chat");
  const embs = form.models.filter((m) => m.purpose === "embedding");
  const chatDef = chats.filter((m) => m.is_default);
  const embDef = embs.filter((m) => m.is_default);
  if (chats.length === 0) {
    ElMessage.warning("至少配置一个对话（chat）模型");
    return false;
  }
  if (chatDef.length !== 1) {
    ElMessage.warning("对话模型需有且仅有一个默认");
    return false;
  }
  if (embs.length > 0 && embDef.length !== 1) {
    ElMessage.warning("若配置了向量（embedding）模型，需有且仅有一个默认");
    return false;
  }
  return true;
}

async function save() {
  if (!form.name?.trim() || !form.api_base?.trim()) {
    ElMessage.warning("请填写名称与 API Base");
    return;
  }
  if (!validateModels()) return;

  const defChat = form.models.find((m) => m.purpose === "chat" && m.is_default);
  if (defChat?.enabled && !(defChat.model_id || "").trim()) {
    ElMessage.warning(
      "请填写默认对话模型的 model_id（Ollama 须与终端执行 ollama list 中的模型名完全一致）"
    );
    return;
  }

  if (!editingId.value) {
    if (providerKind.value === "remote" && !form.api_key?.trim()) {
      ElMessage.warning("远程 API 需填写 API Key");
      return;
    }
    if (providerKind.value === "ollama" && !form.api_key?.trim()) {
      form.api_key = "ollama";
    }
  }

  const payload = {
    name: form.name.trim(),
    api_base: form.api_base.trim(),
    api_key: form.api_key,
    provider_type: form.provider_type,
    models: form.models.map((m) => ({
      display_name: m.display_name,
      model_id: m.model_id,
      purpose: m.purpose,
      is_default: m.is_default,
      enabled: m.enabled,
    })),
  };
  if (editingId.value) {
    await http.patch(`/me/providers/${editingId.value}`, payload);
  } else {
    await http.post("/me/providers", payload);
  }
  ElMessage.success("已保存");
  dialogVisible.value = false;
  await load();
}

async function remove(row: ProviderOut) {
  await http.delete(`/me/providers/${row.id}`);
  ElMessage.success("已删除");
  await load();
}

async function probe(row: ProviderOut) {
  try {
    await http.post(`/me/providers/${row.id}/probe`);
    ElMessage.success("探测成功");
  } catch (e) {
    let raw = e instanceof Error ? e.message : String(e);
    if (axios.isAxiosError(e) && e.response?.data !== undefined) {
      raw =
        typeof e.response.data === "string"
          ? e.response.data
          : JSON.stringify(e.response.data);
    }
    ElMessage.error(messageFromHttpBody(raw));
  }
}

onMounted(load);
</script>

<template>
  <div class="kb-page-shell space-y-4">
    <p class="kb-page-title">模型设置</p>

    <div
      class="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 shadow-sm"
    >
      <el-button type="primary" class="!rounded-lg" round @click="openCreateRemote">
        添加远程 API
      </el-button>
      <el-button class="!rounded-lg" round @click="openCreateOllama">
        添加本地 Ollama
      </el-button>
      <el-tag v-if="readiness.chatReady === true" type="success" effect="plain" round>
        对话模型已就绪
      </el-tag>
      <el-tag v-else-if="readiness.chatReady === false" type="warning" effect="plain" round>
        对话未就绪：{{ readiness.missing.includes("chat") ? "请配置默认 chat" : "" }}
      </el-tag>
      <el-tag v-if="readiness.embeddingReady === true" type="success" effect="plain" round>
        向量已就绪（{{
          readiness.embeddingSource === "local"
            ? "本地 fastembed"
            : readiness.embeddingSource === "api"
              ? "远程 API"
              : "已配置"
        }}，可上传知识库）
      </el-tag>
      <el-tag v-else-if="readiness.embeddingReady === false" type="info" effect="plain" round>
        向量未就绪：请设置 USE_LOCAL_EMBEDDING=true 或配置默认 embedding 模型
      </el-tag>
    </div>

    <p class="text-xs leading-relaxed text-muted-foreground">
      <strong class="text-foreground">远程 API</strong>：同一提供商可同时配置对话与向量模型（用于知识库）。
      <strong class="text-foreground">本地 Ollama</strong>：通常只需对话模型；向量可在环境变量中配置本地 fastembed 或其它远程 Embedding 提供商。
    </p>

    <div class="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <el-table v-loading="loading" :data="list" stripe class="kb-table w-full">
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag v-if="isLocalProvider(row)" size="small" effect="plain" round>
              本地
            </el-tag>
            <el-tag v-else type="info" size="small" effect="plain" round>远程</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="api_base" label="API Base" min-width="220" show-overflow-tooltip />
        <el-table-column prop="provider_type" label="类型" width="140" />
        <el-table-column label="模型数" width="90">
          <template #default="{ row }">{{ row.models?.length ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="probe(row)">探测</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="720px"
      destroy-on-close
      class="provider-dialog"
    >
      <el-alert
        v-if="isOllamaFlow && !editingId"
        type="info"
        :closable="false"
        show-icon
        class="mb-3"
        title="本地 Ollama：API Base 填 http://127.0.0.1:11434 即可（后端会自动接 /v1）。密钥可填 ollama。务必填写 model_id，且与终端 ollama list 中的名称一致。"
      />
      <el-alert
        v-if="!isOllamaFlow && !editingId"
        type="info"
        :closable="false"
        show-icon
        class="mb-3"
        title="远程提供商需填写可访问的 Base URL 与 API Key；下方需各选一个默认的对话模型与向量模型（若使用知识库向量化）。"
      />

      <el-form label-width="108px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如 DeepSeek、硅基流动" />
        </el-form-item>
        <el-form-item label="API Base">
          <el-input
            v-model="form.api_base"
            :placeholder="
              isOllamaFlow
                ? 'http://127.0.0.1:11434（可加或不加 /v1）'
                : 'https://api.openai.com/v1'
            "
          />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="isOllamaFlow ? '可填 ollama' : '必填（编辑时留空表示不修改）'"
          />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.provider_type" :disabled="true">
            <el-option label="OpenAI 兼容" value="openai_compatible" />
          </el-select>
        </el-form-item>
      </el-form>

      <div class="sub-title flex flex-wrap items-center justify-between gap-2">
        <span>模型列表</span>
        <div class="flex flex-wrap gap-2">
          <el-button size="small" round @click="addChatRow">+ 对话模型</el-button>
          <el-button
            v-if="!isOllamaFlow"
            size="small"
            round
            @click="addEmbeddingRow"
          >
            + 向量模型
          </el-button>
        </div>
      </div>
      <el-table :data="form.models" size="small" border class="w-full">
        <el-table-column label="显示名" width="130">
          <template #default="{ row }">
            <el-input v-model="row.display_name" placeholder="展示名称" />
          </template>
        </el-table-column>
        <el-table-column label="model_id" min-width="160">
          <template #default="{ row }">
            <el-input
              v-model="row.model_id"
              :placeholder="
                isOllamaFlow
                  ? '必填：ollama list 中的名称，如 llama3.2'
                  : '如 gpt-4o-mini、deepseek-chat'
              "
            />
          </template>
        </el-table-column>
        <el-table-column label="用途" width="130">
          <template #default="{ row }">
            <el-select v-model="row.purpose" :disabled="isOllamaFlow">
              <el-option label="对话 chat" value="chat" />
              <el-option v-if="!isOllamaFlow" label="向量 embedding" value="embedding" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="默认" width="80">
          <template #default="{ row }">
            <el-switch
              v-model="row.is_default"
              @change="
                (v: boolean) => {
                  if (v) onDefaultToggle(row, row.purpose, true);
                }
              "
            />
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" />
          </template>
        </el-table-column>
        <el-table-column label="" width="56" fixed="right">
          <template #default="{ $index }">
            <el-button
              v-if="form.models.length > 1"
              link
              type="danger"
              @click="removeModelRow($index)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.sub-title {
  font-weight: 600;
  margin: 12px 0 8px;
}
</style>
