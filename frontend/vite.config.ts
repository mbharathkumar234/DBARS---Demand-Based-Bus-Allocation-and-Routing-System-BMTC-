import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    entries: ["src/main.tsx"],
  },
  server: {
    port: 5173,
    watch: {
      ignored: ["**/dist/**"]
    }
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 2000
  }
});
