<script setup lang="ts">
import { RouterView } from "vue-router";
</script>

<template>
  <RouterView />
</template>

<style>
/* 全高布局，子页面用 flex/calc 控制内部滚动 */
html,
body,
#app {
  height: 100%;
  margin: 0;
}
</style>
