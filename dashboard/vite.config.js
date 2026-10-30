import { defineConfig } from "vite";

// The dashboard calls the API through the same origin, so session cookies work regardless of whether the
// browser opened the dashboard as localhost or 127.0.0.1. The dev server forwards /api to the backend.
const apiTarget = process.env.LOGLLAMA_API_URL || "http://127.0.0.1:8000";

export default defineConfig({
  server: {
    proxy: {
      "/api": { target: apiTarget, changeOrigin: false },
    },
  },
  preview: {
    proxy: {
      "/api": { target: apiTarget, changeOrigin: false },
    },
  },
});
