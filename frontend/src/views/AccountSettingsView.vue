<script setup lang="ts">
// 当前用户企业权限：与后端 PATCH /auth/me、GET /auth/me 对齐
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(false);
const saving = ref(false);

const form = reactive({
  branch: "公共",
  role: "user",
  security_level: 4,
  departmentsText: "",
  org_id: "",
});

const levelOptions = [
  { value: 1, label: "1 · 公开（可见公开文档）" },
  { value: 2, label: "2 · 内部" },
  { value: 3, label: "3 · 敏感" },
  { value: 4, label: "4 · 机密（可访问全部密级文档）" },
];

function fillFromUser() {
  const u = auth.user;
  if (!u) return;
  form.branch = u.branch;
  form.role = u.role;
  form.security_level = u.security_level;
  form.departmentsText = u.departments?.length ? u.departments.join("，") : "";
  form.org_id = u.org_id ?? "";
}

onMounted(async () => {
  loading.value = true;
  try {
    await auth.fetchMe();
    fillFromUser();
  } finally {
    loading.value = false;
  }
});

async function save() {
  if (!auth.user) return;
  saving.value = true;
  try {
    const parts = form.departmentsText
      .split(/[,，;；\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    await auth.patchMe({
      branch: form.branch.trim() || "公共",
      role: form.role.trim() || "user",
      security_level: form.security_level,
      departments: parts.length ? parts : [],
      org_id: form.org_id.trim() || null,
    });
    ElMessage.success("已保存，令牌已刷新");
    fillFromUser();
  } catch {
    ElMessage.error("保存失败");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="account-page space-y-4">
    <p class="page-title">账户与权限</p>
    <p class="hint text-sm text-slate-500">
      分行、密级与部门用于控制您能看到的文档与 RAG 检索范围；修改后将自动刷新登录令牌。
      与知识库「组织 ID」一致时可访问对方设为组织共享的知识库。
    </p>

    <el-card v-loading="loading" class="max-w-xl" shadow="never">
      <el-form label-width="100px" @submit.prevent="save">
        <el-form-item label="用户名">
          <el-input :model-value="auth.user?.username" disabled />
        </el-form-item>
        <el-form-item label="分行 / 机构" required>
          <el-input
            v-model="form.branch"
            placeholder="如：上海浦东分行；「公共」表示与全行公开文档匹配"
          />
        </el-form-item>
        <el-form-item label="角色标识">
          <el-input v-model="form.role" placeholder="如：client_manager（便于对接 IAM）" />
        </el-form-item>
        <el-form-item label="密级上限">
          <el-select v-model="form.security_level" class="w-full">
            <el-option
              v-for="opt in levelOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="所属部门">
          <el-input
            v-model="form.departmentsText"
            type="textarea"
            :rows="2"
            placeholder="多个部门可用中文或英文逗号分隔；留空表示不按部门限制匹配"
          />
        </el-form-item>
        <el-form-item label="组织 ID">
          <el-input
            v-model="form.org_id"
            placeholder="与知识库「组织共享」一致时可协作；留空表示仅个人知识库"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="saving">
            保存
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.page-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #0f172a;
}
.hint {
  max-width: 42rem;
  line-height: 1.5;
}
</style>
