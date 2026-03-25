// Axios 实例：JSON API 共用；401 清 token 并跳转登录
import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

const baseURL =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, "") || "/api/v1";

export const http = axios.create({
  baseURL,
  timeout: 120_000,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const t = localStorage.getItem("access_token");
  if (t) {
    config.headers.Authorization = `Bearer ${t}`;
  }
  // FormData 必须由浏览器自动带 multipart boundary；默认 application/json 会导致上传 422/失败
  if (config.data instanceof FormData) {
    config.headers.delete("Content-Type");
  }
  return config;
});

http.interceptors.response.use(
  (r) => r,
  (err: AxiosError<{ detail?: unknown }>) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("access_token");
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
      }
    }
    return Promise.reject(err);
  }
);

export function getApiBaseForFetch(): string {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE.replace(/\/$/, "");
  }
  return "/api/v1";
}
