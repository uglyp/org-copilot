<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { http } from "@/api/http";
import { messageFromHttpBody } from "@/utils/chatError";

const router = useRouter();
const form = reactive({ username: "" });
const loading = ref(false);
const result = ref<{
  message: string;
  reset_token?: string;
  reset_url?: string;
} | null>(null);

async function submit() {
  const u = form.username.trim();
  if (!u) {
    ElMessage.warning("请输入用户名");
    return;
  }
  loading.value = true;
  result.value = null;
  try {
    const { data } = await http.post<{
      message: string;
      reset_token?: string;
      reset_url?: string;
    }>("/auth/forgot-password", { username: u });
    result.value = data;
    ElMessage.success("请求已提交");
  } catch (e: unknown) {
    const raw = e instanceof Error ? e.message : String(e);
    ElMessage.error(messageFromHttpBody(raw));
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="page">
    <el-card class="card" shadow="hover">
      <template #header>忘记密码</template>
      <p class="hint">
        输入注册时的用户名。若系统未配置邮件，请在开发环境开启后端
        <code>PASSWORD_RESET_TOKEN_IN_RESPONSE</code> 以获取重置链接。
      </p>
      <el-form :model="form" label-width="80px" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading">
            申请重置
          </el-button>
          <el-button @click="router.push('/login')">返回登录</el-button>
        </el-form-item>
      </el-form>

      <div v-if="result" class="result">
        <p>{{ result.message }}</p>
        <template v-if="result.reset_url">
          <p class="mt-2 font-medium">重置链接（仅开发环境会返回）</p>
          <el-input :model-value="result.reset_url" readonly type="textarea" :rows="2" />
          <el-button class="mt-2" type="primary" link tag="a" :href="result.reset_url">
            打开重置页
          </el-button>
        </template>
      </div>
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
}
.card {
  width: 440px;
}
.hint {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin: 0 0 16px;
  line-height: 1.5;
}
.result {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
  font-size: 14px;
}
.mt-2 {
  margin-top: 8px;
}
</style>
