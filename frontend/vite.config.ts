import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// lab defaults to :8000; on this machine 8000 is occupied, so dev runs on 8010
// (override with VITE_BACKEND_URL). The wheel serves the built frontend itself.
const BACKEND = process.env.VITE_BACKEND_URL ?? "http://localhost:8010";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/a2a": { target: BACKEND, changeOrigin: true },
      "/mcp": { target: BACKEND, changeOrigin: true },
      "/.well-known": { target: BACKEND, changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
