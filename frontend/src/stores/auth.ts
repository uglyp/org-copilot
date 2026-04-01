// JWT 存 localStorage，请求头由 http 拦截器带上
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { http } from "@/api/http";
import type { MePatchResponse, MeUser } from "@/api/types";

export interface RegisterAclPayload {
  branch?: string;
  role?: string;
  security_level?: number;
  departments?: string[];
  org_id?: string | null;
}

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(localStorage.getItem("access_token"));
  const user = ref<MeUser | null>(null);

  const isAuthenticated = computed(() => !!token.value);

  function setToken(t: string | null) {
    token.value = t;
    if (t) localStorage.setItem("access_token", t);
    else localStorage.removeItem("access_token");
  }

  function applyMePayload(data: MeUser) {
    user.value = {
      id: data.id,
      username: data.username,
      branch: data.branch,
      role: data.role,
      security_level: data.security_level,
      departments: data.departments ?? [],
      org_id: data.org_id ?? null,
    };
  }

  async function fetchMe() {
    const { data } = await http.get<MeUser>("/auth/me");
    applyMePayload(data);
  }

  async function patchMe(
    body: Partial<{
      branch: string;
      role: string;
      security_level: number;
      departments: string[];
      org_id: string | null;
    }>,
  ) {
    const { data } = await http.patch<MePatchResponse>("/auth/me", body);
    setToken(data.access_token);
    applyMePayload(data);
  }

  async function login(username: string, password: string) {
    const { data } = await http.post<{ access_token: string }>("/auth/login", {
      username,
      password,
    });
    setToken(data.access_token);
    await fetchMe();
  }

  async function register(
    username: string,
    password: string,
    acl?: RegisterAclPayload,
  ) {
    const payload: Record<string, unknown> = { username, password };
    if (acl) {
      if (acl.branch != null) payload.branch = acl.branch;
      if (acl.role != null) payload.role = acl.role;
      if (acl.security_level != null) payload.security_level = acl.security_level;
      if (acl.departments != null) payload.departments = acl.departments;
      if (acl.org_id !== undefined) payload.org_id = acl.org_id;
    }
    const { data } = await http.post<{ access_token: string }>(
      "/auth/register",
      payload,
    );
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
    patchMe,
    login,
    register,
    logout,
  };
});
