// 后端 /me/model-readiness，用于进对话页前校验默认 chat 是否配置好
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { http } from "@/api/http";

export const useReadinessStore = defineStore("readiness", () => {
  /** 可进入对话页：默认对话模型已就绪 */
  const chatReady = ref<boolean | null>(null);
  /** 可上传/入库：向量能力已就绪（本地 fastembed 或远程 API） */
  const embeddingReady = ref<boolean | null>(null);
  /** local | api | none */
  const embeddingSource = ref<string | null>(null);
  const missing = ref<string[]>([]);
  const loading = ref(false);

  const ready = computed(() => chatReady.value);

  async function fetchReadiness() {
    loading.value = true;
    try {
      const { data } = await http.get<{
        ready: boolean;
        chat_ready?: boolean;
        embedding_ready?: boolean;
        embedding_source?: string;
        missing: string[];
      }>("/me/model-readiness");
      chatReady.value = data.chat_ready ?? data.ready;
      embeddingReady.value = data.embedding_ready ?? false;
      embeddingSource.value = data.embedding_source ?? null;
      missing.value = data.missing ?? [];
    } finally {
      loading.value = false;
    }
  }

  function reset() {
    chatReady.value = null;
    embeddingReady.value = null;
    embeddingSource.value = null;
    missing.value = [];
  }

  return {
    ready,
    chatReady,
    embeddingReady,
    embeddingSource,
    missing,
    loading,
    fetchReadiness,
    reset,
  };
});
