import { createApp } from "vue";
import { createI18n } from "vue-i18n";
import App from "./App.vue";
import { messages } from "./i18n";
import "./style.css";

const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem("gc:locale") ?? "en",
  fallbackLocale: "en",
  messages,
});

createApp(App).use(i18n).mount("#app");
