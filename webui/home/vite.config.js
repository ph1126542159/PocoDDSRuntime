import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  publicDir: "static",
  build: {
    outDir: "bundle/webui",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: asset => asset.name?.endsWith(".css")
          ? "assets/app-[hash][extname]"
          : "assets/[name]-[hash][extname]"
      }
    }
  }
});
