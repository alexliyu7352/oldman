import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";
import { oldmanWebAliases } from "../../vite.oldman-web";

const rootDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(rootDir, "../../..");

export default defineConfig({
  base: "./",
  plugins: [tailwindcss()],
  resolve: {
    alias: oldmanWebAliases()
  },
  build: {
    emptyOutDir: true,
    manifest: true,
    outDir: resolve(projectRoot, "oldman/apps/admin/static/oldman/admin"),
    rollupOptions: {
      input: {
        main: resolve(rootDir, "src/main.ts")
      }
    }
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"]
  }
});
