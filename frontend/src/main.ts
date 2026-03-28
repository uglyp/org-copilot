// 入口：Pinia → Router → Element Plus（中文）
import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
/* 全量样式：包 exports 未暴露 dist/index.css，按物理路径引入（与官方「全局引入」效果一致） */
import "../node_modules/vue-element-plus-x/dist/index.css";
import zhCn from "element-plus/es/locale/lang/zh-cn";

import App from "./App.vue";
import router from "./router";
import "./index.css";
import "./styles/kb-utilities.css";
import "./styles/kb-theme.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(ElementPlus, { locale: zhCn });
app.mount("#app");
