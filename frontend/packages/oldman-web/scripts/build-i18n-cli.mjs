import { chmod, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "vite";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(scriptDirectory, "..");
const outputName = "oldman-web-i18n.mjs";
const checkedOutput = resolve(packageRoot, "bin", outputName);
const check = process.argv.slice(2).includes("--check");
const temporaryDirectory = check
  ? await mkdtemp(join(tmpdir(), "oldman-web-i18n-"))
  : null;
const outputDirectory = temporaryDirectory ?? resolve(packageRoot, "bin");

try {
  await build({
    build: {
      emptyOutDir: false,
      lib: {
        entry: resolve(scriptDirectory, "i18n-cli-entry.mjs"),
        fileName: () => outputName,
        formats: ["es"]
      },
      minify: false,
      outDir: outputDirectory,
      target: "node20",
      rollupOptions: {
        external: ["typescript", /^node:/],
        output: {
          banner: "#!/usr/bin/env node"
        }
      }
    },
    configFile: false,
    logLevel: "warn",
    root: packageRoot
  });

  const generatedOutput = resolve(outputDirectory, outputName);
  if (check) {
    const [generated, current] = await Promise.all([
      readFile(generatedOutput),
      readFile(checkedOutput).catch(() => Buffer.alloc(0))
    ]);
    if (!generated.equals(current)) {
      throw new Error(`${checkedOutput} is stale; run pnpm build:i18n-cli`);
    }
  } else {
    await chmod(generatedOutput, 0o755);
  }
} finally {
  if (temporaryDirectory) {
    await rm(temporaryDirectory, { recursive: true, force: true });
  }
}
