import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Порт и цель прокси переопределяются из env — так UI-тесты поднимают
// отдельный стенд (:5174 → API :8001) рядом с dev-стендом.
const apiProxy = process.env.SV_API_PROXY ?? "http://127.0.0.1:8000";
const webPort = process.env.SV_WEB_PORT ? Number(process.env.SV_WEB_PORT) : 5173;

export default defineConfig({
  plugins: [react()],
  server: {
    port: webPort,
    // Заданный порт (e2e-стенд) — строго: не уезжать молча на соседний; в dev — как раньше
    strictPort: Boolean(process.env.SV_WEB_PORT),
    proxy: {
      // Dev proxy to FastAPI so the frontend calls /api without CORS
      "/api": apiProxy,
    },
  },
});
