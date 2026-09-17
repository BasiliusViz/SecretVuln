import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Dev proxy to FastAPI so the frontend calls /api without CORS
      "/api": "http://127.0.0.1:8000",
    },
  },
});
