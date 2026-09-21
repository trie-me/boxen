import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/boxen/static", emptyOutDir: true, rollupOptions: { output: { manualChunks: { markdown: ['markdown-it', 'dompurify'], react: ['react', 'react-dom', 'react-router-dom'] } } } },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
