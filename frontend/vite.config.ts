import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",          // Required for Capacitor: assets resolve relative to index.html
  optimizeDeps: {
    entries: ["src/main.tsx"],
  },
  server: {
    port: 5173,
    watch: {
      ignored: ["**/android/**", "**/dist/**"]
    }
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 2000
  }
});
