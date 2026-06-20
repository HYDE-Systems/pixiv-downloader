import { defineConfig } from "vite";

// 開発時は /api をバックエンドコンテナへプロキシする。
export default defineConfig({
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.BACKEND_URL || "http://backend:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
