<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { http } from "@/api/http";
import { messageFromHttpBody } from "@/utils/chatError";

const route = useRoute();
const router = useRouter();
const form = reactive({
  token: "",
  new_password: "",
  new_password2: "",
});
const loading = ref(false);

onMounted(() => {
  const q = route.query.token;
  if (typeof q === "string" && q) {
    form.token = q;
  }
});

async function submit() {
  if (!form.token.trim()) {
    ElMessage.warning("缺少重置令牌，请从邮件或忘记密码页进入");
    return;
  }
  if (form.new_password !== form.new_password2) {
    ElMessage.warning("两次输入的新密码不一致");
    return;
  }
  loading.value = true;
  try {
    await http.post("/auth/reset-password", {
      token: form.token.trim(),
      new_password: form.new_password,
    });
    ElMessage.success("密码已更新，请登录");
    await router.replace("/login");
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
      <template #header>设置新密码</template>
      <el-form :model="form" label-width="100px" @submit.prevent="submit">
        <el-form-item label="重置令牌">
          <el-input
            v-model="form.token"
            type="textarea"
            :rows="2"
            placeholder="通常由链接自动填入"
          />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input
            v-model="form.new_password"
            type="password"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input
            v-model="form.new_password2"
            type="password"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading">
            确认修改
          </el-button>
          <el-button @click="router.push('/login')">返回登录</el-button>
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
}
.card {
  width: 440px;
}
</style>
