<script setup lang="ts">
// marked 渲染后 DOMPurify 消毒，再 v-html（勿直接绑模型 HTML）
import { computed } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

const props = defineProps<{
  content: string;
}>();

const html = computed(() => {
  const raw = marked.parse(props.content || "") as string;
  return DOMPurify.sanitize(raw);
});
</script>

<template>
  <div class="ai-md" v-html="html" />
</template>

<style scoped>
.ai-md {
  font-size: 0.875rem;
  line-height: 1.6;
  color: hsl(var(--foreground));
}

.ai-md :deep(p) {
  margin: 0 0 0.65em;
}

.ai-md :deep(p:last-child) {
  margin-bottom: 0;
}

.ai-md :deep(ul),
.ai-md :deep(ol) {
  margin: 0.35em 0 0.65em;
  padding-left: 1.25rem;
}

.ai-md :deep(li) {
  margin: 0.2em 0;
}

.ai-md :deep(pre) {
  margin: 0.5em 0;
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  background: hsl(var(--muted));
  border: 1px solid hsl(var(--border));
  overflow-x: auto;
  font-size: 0.8125rem;
}

.ai-md :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8125em;
}

.ai-md :deep(p > code),
.ai-md :deep(li > code) {
  padding: 0.1em 0.35em;
  border-radius: 0.25rem;
  background: hsl(var(--muted));
  border: 1px solid hsl(var(--border));
}

.ai-md :deep(pre code) {
  padding: 0;
  background: transparent;
  border: none;
  font-size: inherit;
}

.ai-md :deep(a) {
  color: hsl(var(--primary));
  text-decoration: underline;
  text-underline-offset: 2px;
}

.ai-md :deep(hr) {
  margin: 0.75em 0;
  border: none;
  border-top: 1px solid hsl(var(--border));
}

.ai-md :deep(blockquote) {
  margin: 0.5em 0;
  padding-left: 0.75rem;
  border-left: 3px solid hsl(var(--border));
  color: hsl(var(--muted-foreground));
}
</style>
