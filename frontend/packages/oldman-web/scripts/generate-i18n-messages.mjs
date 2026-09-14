import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  extractMessageManifest,
  repositoryPath
} from "./i18n-extractor.mjs";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(scriptDirectory, "..");
const defaultRepositoryRoot = resolve(scriptDirectory, "../../../..");
const defaultSourceRoots = [
  resolve(packageRoot, "src"),
  resolve(defaultRepositoryRoot, "frontend/apps/admin/src")
];
const defaultOutput = resolve(
  defaultRepositoryRoot,
  "oldman/i18n/data/oldman_web_messages.json"
);

const options = parseArguments(process.argv.slice(2));
const manifest = await extractMessageManifest(
  options.sourceRoots,
  options.repositoryRoot
);
const serializedManifest = `${JSON.stringify(manifest, null, 2)}\n`;

if (options.check) {
  const current = await readFile(options.output, "utf8").catch(() => "");
  if (current !== serializedManifest) {
    throw new Error(
      `${repositoryPath(options.output, options.repositoryRoot)} is stale; run pnpm generate:i18n-messages`
    );
  }
} else {
  await mkdir(dirname(options.output), { recursive: true });
  await writeFile(options.output, serializedManifest, "utf8");
}

/**
 * Parse the explicit generator CLI used by package scripts and tests.
 */
function parseArguments(argumentsList) {
  const parsed = {
    check: false,
    output: defaultOutput,
    repositoryRoot: defaultRepositoryRoot,
    sourceRoots: []
  };

  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument === "--check") {
      parsed.check = true;
      continue;
    }
    if (
      argument === "--output"
      || argument === "--repository-root"
      || argument === "--source-root"
    ) {
      const value = argumentsList[index + 1];
      if (!value) throw new Error(`${argument} requires a path`);
      index += 1;
      const resolvedValue = resolve(value);
      if (argument === "--output") parsed.output = resolvedValue;
      if (argument === "--repository-root") {
        parsed.repositoryRoot = resolvedValue;
      }
      if (argument === "--source-root") {
        parsed.sourceRoots.push(resolvedValue);
      }
      continue;
    }
    throw new Error(`Unknown argument: ${argument}`);
  }
  return {
    ...parsed,
    sourceRoots:
      parsed.sourceRoots.length > 0
        ? parsed.sourceRoots
        : defaultSourceRoots
  };
}
