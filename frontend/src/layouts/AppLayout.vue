<script setup lang="ts">
// 顶栏导航 + 主内容区（router-view）
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessageBox } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import { useReadinessStore } from "@/stores/readiness";

const auth = useAuthStore();
const readiness = useReadinessStore();
const route = useRouter();
const current = useRoute();

const active = computed(() => current.path);

async function logout() {
  await ElMessageBox.confirm("确定退出登录？", "提示", { type: "warning" });
  auth.logout();
  readiness.reset();
  route.push("/login");
}
</script>

<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="brand-wrap">
        <span class="brand-mark" aria-hidden="true" />
        <div class="brand">知识库 Copilot</div>
      </div>
      <el-menu
        :default-active="active"
        mode="horizontal"
        router
        class="menu"
        :ellipsis="false"
      >
        <el-menu-item index="/knowledge">知识库</el-menu-item>
        <el-menu-item index="/chat">对话</el-menu-item>
        <el-menu-item index="/settings/models">模型设置</el-menu-item>
        <el-menu-item index="/settings/account">账户与权限</el-menu-item>
        <el-menu-item index="/settings/usage">用量统计</el-menu-item>
      </el-menu>
      <div class="user">
        <span v-if="auth.user" class="user-name">{{ auth.user.username }}</span>
        <el-button link type="primary" @click="logout">退出</el-button>
      </div>
    </el-header>
    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  flex-direction: column;
  background: var(--kb-page-bg, linear-gradient(165deg, #f4f7ff 0%, #f8fafc 100%));
}
.header {
  display: flex;
  align-items: center;
  gap: 24px;
  height: 56px !important;
  padding: 0 28px !important;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
}
.brand-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-mark {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
}
.brand {
  font-weight: 700;
  font-size: 1.05rem;
  letter-spacing: -0.02em;
  color: #0f172a;
  white-space: nowrap;
}
.menu {
  flex: 1;
  border-bottom: none !important;
  background: transparent !important;
}
.menu :deep(.el-menu-item) {
  font-weight: 500;
}
.user {
  display: flex;
  align-items: center;
  gap: 12px;
  white-space: nowrap;
}
.user-name {
  font-size: 13px;
  color: #64748b;
}
.main {
  padding: 24px 28px 32px;
  max-width: 1320px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}
</style>
