<script setup lang="ts">
// 注册成功后与登录相同：拿 token 再进应用；可选填企业权限（与后端 RegisterBody 一致）
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore, type RegisterAclPayload } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();

const form = reactive({ username: "", password: "", password2: "" });
const adv = reactive({
  branch: "",
  role: "",
  security_level: undefined as number | undefined,
  departmentsText: "",
  org_id: "",
});
const loading = ref(false);

async function submit() {
  if (form.password !== form.password2) {
    ElMessage.warning("两次密码不一致");
    return;
  }
  loading.value = true;
  try {
    const acl: RegisterAclPayload = {};
    if (adv.branch.trim()) acl.branch = adv.branch.trim();
    if (adv.role.trim()) acl.role = adv.role.trim();
    if (adv.security_level != null) acl.security_level = adv.security_level;
    const deptParts = adv.departmentsText
      .split(/[,，;；\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (deptParts.length) acl.departments = deptParts;
    if (adv.org_id.trim()) acl.org_id = adv.org_id.trim();

    const hasAcl = Object.keys(acl).length > 0;
    await auth.register(form.username, form.password, hasAcl ? acl : undefined);
    await router.replace("/chat");
    ElMessage.success("注册成功");
  } catch {
    ElMessage.error("注册失败，用户名可能已被占用");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="page">
    <el-card class="card" shadow="hover">
      <template #header>注册</template>
      <el-form :model="form" label-width="88px" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input
            v-model="form.password2"
            type="password"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>

        <el-collapse class="reg-adv">
          <el-collapse-item title="企业权限（可选，注册后也可在「账户与权限」修改）" name="adv">
            <el-form-item label="分行">
              <el-input v-model="adv.branch" placeholder="默认：公共" />
            </el-form-item>
            <el-form-item label="角色">
              <el-input v-model="adv.role" placeholder="默认：user" />
            </el-form-item>
            <el-form-item label="密级上限">
              <el-select
                v-model="adv.security_level"
                clearable
                placeholder="默认：4"
                class="w-full"
              >
                <el-option :value="1" label="1 公开" />
                <el-option :value="2" label="2 内部" />
                <el-option :value="3" label="3 敏感" />
                <el-option :value="4" label="4 机密" />
              </el-select>
            </el-form-item>
            <el-form-item label="部门">
              <el-input
                v-model="adv.departmentsText"
                type="textarea"
                :rows="2"
                placeholder="多个部门用逗号分隔"
              />
            </el-form-item>
            <el-form-item label="组织 ID">
              <el-input v-model="adv.org_id" placeholder="与共享知识库的组织 ID 一致" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>

        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading">
            注册
          </el-button>
          <el-button @click="$router.push('/login')">已有账号</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #f0f4ff 0%, #fff 50%);
  padding: 24px 16px;
}
.card {
  width: 100%;
  max-width: 440px;
}
.reg-adv {
  margin-bottom: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.reg-adv :deep(.el-collapse-item__header) {
  padding-left: 12px;
  font-size: 13px;
}
.reg-adv :deep(.el-collapse-item__content) {
  padding-bottom: 4px;
}
</style>
