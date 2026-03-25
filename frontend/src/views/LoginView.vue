<script setup lang="ts">
// 登录成功后回到 redirect 或默认知识库页
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

const form = reactive({ username: "", password: "" });
const loading = ref(false);

async function submit() {
  loading.value = true;
  try {
    await auth.login(form.username, form.password);
    const redirect = (route.query.redirect as string) || "/knowledge";
    await router.replace(redirect);
  } catch (e: unknown) {
    ElMessage.error("登录失败，请检查用户名与密码");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="page">
    <el-card class="card" shadow="hover">
      <template #header>登录</template>
      <el-form :model="form" label-width="80px" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading">
            登录
          </el-button>
          <el-button @click="$router.push('/register')">注册账号</el-button>
          <el-button link type="primary" @click="$router.push('/forgot-password')">
            忘记密码
          </el-button>
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
