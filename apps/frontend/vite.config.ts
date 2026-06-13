import vue from "@vitejs/plugin-vue";
import path from "node:path";
import { defineConfig } from "vite";

const HUB = process.env.COLLAB_HTTP_URL ?? "http://127.0.0.1:4001";

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: Number(process.env.FRONTEND_PORT ?? 5173),
    proxy: {
      "/api": { target: HUB, changeOrigin: true },
      "/ws": { target: HUB.replace(/^http/, "ws"), ws: true, changeOrigin: true },
    },
  },
});
