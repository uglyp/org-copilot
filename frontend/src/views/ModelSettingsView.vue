<script setup lang="ts">
// OpenAI 兼容提供商与 chat/embedding 模型行编辑
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { http } from "@/api/http";
import type { LLMModelRow, ProviderOut } from "@/api/types";
import { useReadinessStore } from "@/stores/readiness";

const readiness = useReadinessStore();
const list = ref<ProviderOut[]>([]);
const loading = ref(false);

const dialogVisible = ref(false);
const editingId = ref<number | null>(null);

const form = reactive({
  name: "",
  api_base: "",
  api_key: "",
  provider_type: "openai_compatible",
  models: [] as LLMModelRow[],
});

function defaultModels(): LLMModelRow[] {
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

function openCreate() {
  editingId.value = null;
  Object.assign(form, {
    name: "",
    api_base: "",
    api_key: "",
    provider_type: "openai_compatible",
    models: defaultModels(),
  });
  dialogVisible.value = true;
}

function openEdit(row: ProviderOut) {
  editingId.value = row.id;
  form.name = row.name;
  form.api_base = row.api_base;
  form.api_key = "";
  form.provider_type = row.provider_type;
  form.models = row.models.map((m) => ({ ...m }));
  dialogVisible.value = true;
}

async function save() {
  if (!form.name || !form.api_base) {
    ElMessage.warning("请填写名称与 API Base");
    return;
  }
  const chatDef = form.models.filter((m) => m.purpose === "chat" && m.is_default);
  const embDef = form.models.filter((m) => m.purpose === "embedding" && m.is_default);
  if (chatDef.length !== 1 || embDef.length !== 1) {
    ElMessage.warning("每种用途需且仅能有一个默认模型");
    return;
  }
  const payload = {
    name: form.name,
    api_base: form.api_base,
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
    if (!form.api_key) {
      ElMessage.warning("请填写 API Key");
      return;
    }
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
  } catch {
    ElMessage.error("探测失败，请检查模型与密钥");
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
      <el-button type="primary" class="!rounded-lg" round @click="openCreate">
        新增提供商
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

    <div class="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
    <el-table
      v-loading="loading"
      :data="list"
      stripe
      class="kb-table w-full"
    >
      <el-table-column prop="name" label="名称" width="160" />
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
      :title="editingId ? '编辑提供商' : '新增提供商'"
      width="640px"
      destroy-on-close
    >
      <el-form label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="API Base">
          <el-input v-model="form.api_base" placeholder="https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.provider_type">
            <el-option label="OpenAI 兼容" value="openai_compatible" />
          </el-select>
        </el-form-item>
      </el-form>

      <div class="sub-title">模型列表</div>
      <el-table :data="form.models" size="small" border>
        <el-table-column label="显示名" width="120">
          <template #default="{ row }">
            <el-input v-model="row.display_name" />
          </template>
        </el-table-column>
        <el-table-column label="model_id" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.model_id" placeholder="gpt-4o-mini" />
          </template>
        </el-table-column>
        <el-table-column label="用途" width="120">
          <template #default="{ row }">
            <el-select v-model="row.purpose">
              <el-option label="对话 chat" value="chat" />
              <el-option label="向量 embedding" value="embedding" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="默认" width="70">
          <template #default="{ row }">
            <el-switch v-model="row.is_default" />
          </template>
        </el-table-column>
        <el-table-column label="启用" width="70">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" />
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
