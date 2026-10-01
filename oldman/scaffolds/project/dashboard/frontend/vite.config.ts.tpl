import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/dist/" : "/",
  plugins: [tailwindcss()],
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    manifest: true,
    // ApexCharts alone is about 580 kB; oldman-web loads it only on pages that have a chart.
    // Any other chunk past 600 kB still gets Vite's warning.
    chunkSizeWarningLimit: 600,
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
