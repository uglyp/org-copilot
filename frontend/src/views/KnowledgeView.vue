<script setup lang="ts">
// 知识库 CRUD + 文档上传列表（上传走 multipart，axios 会去掉 Content-Type 让浏览器带 boundary）
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { UploadFile } from "element-plus";
import type { AxiosError } from "axios";
import { Picture } from "@element-plus/icons-vue";
import { http } from "@/api/http";
import type { DocumentOut, KnowledgeBaseOut } from "@/api/types";

const kbs = ref<KnowledgeBaseOut[]>([]);
const activeKbId = ref<number | null>(null);
const docs = ref<DocumentOut[]>([]);
const loading = ref(false);
const uploadLoading = ref(false);

const kbForm = ref({ name: "", description: "" });
const createKbVisible = ref(false);

const activeKb = computed(() => kbs.value.find((k) => k.id === activeKbId.value));

async function loadKbs() {
  loading.value = true;
  try {
    const { data } = await http.get<KnowledgeBaseOut[]>("/knowledge-bases");
    kbs.value = data;
    if (!activeKbId.value && data.length) {
      activeKbId.value = data[0].id;
      await loadDocs();
    } else if (activeKbId.value) {
      await loadDocs();
    }
  } finally {
    loading.value = false;
  }
}

async function loadDocs() {
  if (!activeKbId.value) {
    docs.value = [];
    return;
  }
  const { data } = await http.get<DocumentOut[]>(
    `/knowledge-bases/${activeKbId.value}/documents`
  );
  docs.value = data;
}

async function createKb() {
  if (!kbForm.value.name.trim()) {
    ElMessage.warning("请填写知识库名称");
    return;
  }
  await http.post("/knowledge-bases", kbForm.value);
  ElMessage.success("已创建");
  createKbVisible.value = false;
  kbForm.value = { name: "", description: "" };
  await loadKbs();
}

async function onKbChange(id: number) {
  activeKbId.value = id;
  await loadDocs();
}

function handleKbSelect(index: string) {
  void onKbChange(Number(index));
}

async function onFileChange(uploadFile: UploadFile) {
  if (!activeKbId.value || !uploadFile.raw) return;
  uploadLoading.value = true;
  try {
    const fd = new FormData();
    fd.append("file", uploadFile.raw);
    await http.post(`/knowledge-bases/${activeKbId.value}/documents`, fd);
    ElMessage.success("已上传，后台处理中");
    await loadDocs();
  } catch (e: unknown) {
    const err = e as AxiosError<{ detail?: string | { message?: string } }>;
    const status = err.response?.status;
    if (status === 412) {
      ElMessage.error("请先完成向量/模型配置后再上传");
    } else {
      const d = err.response?.data?.detail;
      const msg =
        typeof d === "string"
          ? d
          : d && typeof d === "object" && "message" in d && d.message
            ? String(d.message)
            : err.message || "上传失败";
      ElMessage.error(msg);
    }
  } finally {
    uploadLoading.value = false;
  }
}

async function removeDoc(row: DocumentOut) {
  await ElMessageBox.confirm(`删除文档「${row.filename}」？`, "确认", {
    type: "warning",
  });
  await http.delete(`/knowledge-bases/${activeKbId.value}/documents/${row.id}`);
  ElMessage.success("已删除");
  await loadDocs();
}

onMounted(loadKbs);
</script>

<template>
  <div class="kb-page-shell space-y-4">
    <p class="kb-page-title">知识库</p>
    <div class="flex flex-wrap items-center gap-2">
      <el-button type="primary" class="!rounded-lg" round @click="createKbVisible = true">
        新建知识库
      </el-button>
    </div>

    <div class="grid gap-5 lg:grid-cols-12 lg:items-stretch">
      <aside
        class="flex min-h-[320px] flex-col overflow-hidden rounded-xl border border-border bg-card shadow-sm lg:col-span-5"
      >
        <div
          class="border-b border-border px-4 py-3 text-sm font-semibold text-foreground"
        >
          知识库列表
        </div>
        <div v-loading="loading" class="min-h-0 flex-1 overflow-auto p-2">
          <el-menu
            class="border-0 !bg-transparent"
            :default-active="String(activeKbId ?? '')"
            @select="handleKbSelect"
          >
            <el-menu-item v-for="k in kbs" :key="k.id" :index="String(k.id)">
              {{ k.name }}
            </el-menu-item>
          </el-menu>
          <el-empty v-if="!kbs.length" description="暂无知识库" />
        </div>
      </aside>

      <section
        class="flex min-h-[320px] flex-col overflow-hidden rounded-xl border border-border bg-card shadow-sm lg:col-span-7"
      >
        <div
          class="border-b border-border px-4 py-3 text-sm font-semibold text-foreground"
        >
          文档 — {{ activeKb?.name || "未选择" }}
        </div>
        <div class="flex min-h-0 flex-1 flex-col p-4">
          <div v-if="activeKbId" class="upload-row mb-3">
            <el-upload
              :auto-upload="false"
              :show-file-list="false"
              accept=".pdf,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,.gif,.bmp"
              @change="onFileChange"
            >
              <el-button type="primary" class="!rounded-lg" :loading="uploadLoading">
                上传文档或图片
              </el-button>
            </el-upload>
          </div>
          <el-table v-if="activeKbId" :data="docs" stripe class="kb-table w-full">
            <el-table-column prop="filename" label="文件名" min-width="200">
              <template #default="{ row }">
                <span class="inline-flex items-center gap-1.5">
                  <el-icon v-if="row.modality === 'image'" class="text-primary" :title="'图像（OCR 入库）'">
                    <Picture />
                  </el-icon>
                  {{ row.filename }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="120" />
            <el-table-column label="错误" min-width="160">
              <template #default="{ row }">
                <span class="err">{{ row.error_message }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button link type="danger" @click="removeDoc(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="请选择左侧知识库" />
        </div>
      </section>
    </div>

    <el-dialog v-model="createKbVisible" title="新建知识库" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="kbForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="kbForm.description" type="textarea" rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createKbVisible = false">取消</el-button>
        <el-button type="primary" @click="createKb">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.upload-row {
  margin-bottom: 0;
}
.err {
  color: var(--el-color-danger);
  font-size: 12px;
}
</style>
