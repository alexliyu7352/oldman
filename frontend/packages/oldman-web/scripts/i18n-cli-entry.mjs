import { resolve } from "node:path";

import { compilePoCatalog } from "../src/core/i18n/po.ts";
import { extractMessageManifest } from "./i18n-extractor.mjs";

await main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
});

/**
 * Dispatch the packaged PO compiler and TypeScript AST extractor.
 */
async function main() {
  const [command, ...argumentsList] = process.argv.slice(2);
  if (command === "compile-po") {
    await compilePo(argumentsList);
    return;
  }
  if (command === "extract") {
    await extractMessages(argumentsList);
    return;
  }
  throw new Error(
    "Usage: oldman-web-i18n <compile-po|extract> [options]"
  );
}

/**
 * Compile a PO document received on stdin into one JSON catalog.
 */
async function compilePo(argumentsList) {
  let fallbackLocale = "en";
  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument !== "--fallback-locale") {
      throw new Error(`Unknown compile-po argument: ${argument}`);
    }
    const value = argumentsList[index + 1];
    if (!value) throw new Error("--fallback-locale requires a value");
    fallbackLocale = value;
    index += 1;
  }

  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const content = Buffer.concat(chunks).toString("utf8");
  const catalog = compilePoCatalog(content, fallbackLocale);
  process.stdout.write(`${JSON.stringify(catalog)}\n`);
}

/**
 * Extract static i18n calls from one or more project source roots.
 */
async function extractMessages(argumentsList) {
  let projectRoot = "";
  const sourceRoots = [];
  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument !== "--project-root" && argument !== "--source-root") {
      throw new Error(`Unknown extract argument: ${argument}`);
    }
    const value = argumentsList[index + 1];
    if (!value) throw new Error(`${argument} requires a path`);
    index += 1;
    if (argument === "--project-root") {
      if (projectRoot) {
        throw new Error("--project-root may only be specified once");
      }
      projectRoot = resolve(value);
    } else {
      sourceRoots.push(resolve(value));
    }
  }
  if (!projectRoot) throw new Error("extract requires --project-root");
  if (sourceRoots.length === 0) {
    throw new Error("extract requires at least one --source-root");
  }

  const manifest = await extractMessageManifest(sourceRoots, projectRoot);
  process.stdout.write(`${JSON.stringify(manifest)}\n`);
}
