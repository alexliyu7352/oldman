import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/dist/" : "/",
  plugins: [tailwindcss()],
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: "src/main.ts"
    }
  },
  server: {
    origin: "http://localhost:5173",
    port: 5173,
    strictPort: true
  }
}));
