<script setup lang="ts">
// 注册成功后与登录相同：拿 token 再进应用
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();

const form = reactive({ username: "", password: "", password2: "" });
const loading = ref(false);

async function submit() {
  if (form.password !== form.password2) {
    ElMessage.warning("两次密码不一致");
    return;
  }
  loading.value = true;
  try {
    await auth.register(form.username, form.password);
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
      <el-form :model="form" label-width="80px" @submit.prevent="submit">
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
}
.card {
  width: 400px;
}
</style>
