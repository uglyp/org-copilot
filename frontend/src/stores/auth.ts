// JWT 存 localStorage，请求头由 http 拦截器带上
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { http } from "@/api/http";

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(localStorage.getItem("access_token"));
  const user = ref<{ id: number; username: string } | null>(null);

  const isAuthenticated = computed(() => !!token.value);

  function setToken(t: string | null) {
    token.value = t;
    if (t) localStorage.setItem("access_token", t);
    else localStorage.removeItem("access_token");
  }

  async function fetchMe() {
    const { data } = await http.get<{ id: number; username: string }>("/auth/me");
    user.value = data;
  }

  async function login(username: string, password: string) {
    const { data } = await http.post<{ access_token: string }>("/auth/login", {
      username,
      password,
    });
    setToken(data.access_token);
    await fetchMe();
  }

  async function register(username: string, password: string) {
    const { data } = await http.post<{ access_token: string }>("/auth/register", {
      username,
      password,
    });
    setToken(data.access_token);
    await fetchMe();
  }

  function logout() {
    setToken(null);
    user.value = null;
  }

  return {
    token,
    user,
    isAuthenticated,
    setToken,
    fetchMe,
    login,
    register,
    logout,
  };
});
