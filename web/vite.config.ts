import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Vite serves the UI in development and proxies /api to the Python process,
  // so the browser only ever sees one origin. In production FastAPI serves
  // dist/ itself. Either way there is no CORS configuration to get wrong.
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
