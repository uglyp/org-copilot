// 路由守卫：登录态、进入对话前拉模型就绪状态
import { createRouter, createWebHistory } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import { useReadinessStore } from "@/stores/readiness";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { guestOnly: true },
    },
    {
      path: "/register",
      name: "register",
      component: () => import("@/views/RegisterView.vue"),
      meta: { guestOnly: true },
    },
    {
      path: "/forgot-password",
      name: "forgot-password",
      component: () => import("@/views/ForgotPasswordView.vue"),
      meta: { guestOnly: true },
    },
    {
      path: "/reset-password",
      name: "reset-password",
      component: () => import("@/views/ResetPasswordView.vue"),
      meta: { guestOnly: true },
    },
    {
      path: "/",
      component: () => import("@/layouts/AppLayout.vue"),
      meta: { requiresAuth: true },
      children: [
        { path: "", redirect: "/knowledge" },
        {
          path: "settings/models",
          name: "model-settings",
          component: () => import("@/views/ModelSettingsView.vue"),
        },
        {
          path: "settings/usage",
          name: "usage-stats",
          component: () => import("@/views/UsageStatsView.vue"),
        },
        {
          path: "settings/account",
          name: "account-settings",
          component: () => import("@/views/AccountSettingsView.vue"),
        },
        {
          path: "admin/system",
          name: "admin-system",
          component: () => import("@/views/AdminSystemView.vue"),
          meta: { requiresAdmin: true },
        },
        {
          path: "knowledge",
          name: "knowledge",
          component: () => import("@/views/KnowledgeView.vue"),
        },
        {
          path: "chat/:conversationId?",
          name: "chat",
          component: () => import("@/views/ChatView.vue"),
          meta: { requiresChatReady: true },
        },
      ],
    },
  ],
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  const readiness = useReadinessStore();

  if (to.meta.guestOnly && auth.token) {
    return { path: "/knowledge" };
  }

  if (to.meta.requiresAuth) {
    if (!auth.token) {
      return { name: "login", query: { redirect: to.fullPath } };
    }
    if (!auth.user) {
      try {
        await auth.fetchMe();
      } catch {
        auth.logout();
        return { name: "login", query: { redirect: to.fullPath } };
      }
    }
  }

  if (to.meta.requiresChatReady && auth.token) {
    await readiness.fetchReadiness();
    if (readiness.chatReady === false) {
      return {
        name: "model-settings",
        query: { ...to.query, reason: "model" },
      };
    }
  }

  if (to.meta.requiresAdmin) {
    if (!auth.user) {
      return { name: "login", query: { redirect: to.fullPath } };
    }
    if (!auth.isAdmin) {
      ElMessage.warning("无系统管理权限");
      return { path: "/knowledge" };
    }
  }

  return true;
});

export default router;
