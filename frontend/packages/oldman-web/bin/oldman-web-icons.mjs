#!/usr/bin/env node

import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const iconSets = {
  bx: require("@iconify-json/bx/icons.json"),
  mdi: require("@iconify-json/mdi/icons.json"),
  ri: require("@iconify-json/ri/icons.json")
};
const ICON_CLASS_PATTERN = /\b(?:ri|mdi|bx|bxs|bxl)-[a-z0-9-]+\b/g;
const ICON_UTILITY_CLASSES = new Set(["mdi-spin"]);
const SOURCE_EXTENSIONS = new Set([".cjs", ".html", ".jinja", ".jinja2", ".js", ".mjs", ".py", ".tpl", ".ts", ".tsx"]);
const SKIPPED_DIRECTORIES = new Set([
  ".git",
  "__pycache__",
  "coverage",
  "dist",
  "generated",
  "node_modules",
  "public",
  "static",
  "test",
  "tests",
  "theme",
  "vendor"
]);

const options = parseArguments(process.argv.slice(2));
const excludedIconClasses = options.excludeShared ? collectSharedIconClasses() : new Set();
const iconClasses = new Set(
  [...collectIconClasses(options.sources, options.excluded)].filter((iconClass) => !excludedIconClasses.has(iconClass))
);
const css = renderIconStyles(iconClasses);

if (options.check) {
  if (!existsSync(options.output) || readFileSync(options.output, "utf8") !== css) {
    throw new Error(`Generated icon CSS is stale: ${options.output}`);
  }
  console.log(`verified ${iconClasses.size} generated icon styles: ${options.output}`);
} else {
  mkdirSync(dirname(options.output), { recursive: true });
  writeFileSync(options.output, css, "utf8");
  console.log(`generated ${iconClasses.size} icon styles: ${options.output}`);
}

function parseArguments(args) {
  let check = false;
  let excludeShared = false;
  let output = null;
  const sources = [];
  const excluded = [];

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--check") {
      check = true;
      continue;
    }
    if (argument === "--exclude-shared") {
      excludeShared = true;
      continue;
    }
    if (argument === "--output" || argument === "--source" || argument === "--exclude") {
      const value = args[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`${argument} requires a path`);
      index += 1;
      if (argument === "--output") output = resolve(value);
      else if (argument === "--exclude") excluded.push(resolve(value));
      else sources.push(resolve(value));
      continue;
    }
    if (argument === "--help" || argument === "-h") {
      printUsage();
      process.exit(0);
    }
    throw new Error(`Unknown argument: ${argument}`);
  }

  if (!output || sources.length === 0) {
    printUsage();
    throw new Error("--output and at least one --source are required");
  }
  return { check, excludeShared, excluded, output, sources };
}

function printUsage() {
  console.log(
    "Usage: oldman-web-icons --output <file> --source <path> [--source <path> ...] [--exclude <path> ...] [--exclude-shared] [--check]"
  );
}

function collectSharedIconClasses() {
  const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const candidates = [resolve(packageRoot, "src/styles/icons.css"), resolve(packageRoot, "dist/styles/icons.css")];
  const sharedIconsPath = candidates.find((candidate) => existsSync(candidate));
  if (!sharedIconsPath) throw new Error("Shared oldman-web icon inventory does not exist");

  const source = readFileSync(sharedIconsPath, "utf8");
  return new Set([...source.matchAll(ICON_CLASS_PATTERN)].map((match) => match[0]));
}

function collectIconClasses(sourcePaths, excludedPaths = []) {
  const sourceFiles = new Set();
  for (const sourcePath of sourcePaths) collectSourceFiles(sourcePath, sourceFiles, true, excludedPaths);

  const iconClasses = new Set();
  for (const filePath of [...sourceFiles].sort()) {
    const source = readFileSync(filePath, "utf8");
    for (const match of source.matchAll(ICON_CLASS_PATTERN)) iconClasses.add(match[0]);
  }
  return new Set([...iconClasses].sort());
}

function collectSourceFiles(filePath, files, explicitSource = false, excludedPaths = []) {
  if (!existsSync(filePath)) throw new Error(`Icon source does not exist: ${filePath}`);
  // 排除的是"另有自己图标表"的子树（可插拔的 App），不是为了少扫文件。
  if (excludedPaths.some((excluded) => filePath === excluded || filePath.startsWith(`${excluded}/`))) return;
  const stats = statSync(filePath);
  if (stats.isDirectory()) {
    if (!explicitSource && SKIPPED_DIRECTORIES.has(filePath.split("/").at(-1))) return;
    for (const name of readdirSync(filePath).sort()) {
      collectSourceFiles(resolve(filePath, name), files, false, excludedPaths);
    }
    return;
  }
  if (!stats.isFile() || isIgnoredSourceFile(filePath)) return;
  files.add(filePath);
}

function isIgnoredSourceFile(filePath) {
  const normalized = filePath.replaceAll("\\", "/");
  const fileName = normalized.split("/").at(-1) ?? "";
  if (
    fileName.includes(".test.")
    || fileName.includes(".spec.")
    || fileName.startsWith("test_")
    || fileName.endsWith("_test.py")
    || fileName.endsWith(".d.ts")
  ) return true;
  const extensionIndex = fileName.lastIndexOf(".");
  const extension = extensionIndex >= 0 ? fileName.slice(extensionIndex) : "";
  return !SOURCE_EXTENSIONS.has(extension);
}

function renderIconStyles(iconClasses) {
  const renderableIconClasses = [...iconClasses].filter((iconClass) => !ICON_UTILITY_CLASSES.has(iconClass));
  const iconSelector = renderableIconClasses.map((iconClass) => `.${iconClass}::before`).join(",\n");
  const blocks = [
    "/* Generated by oldman-web-icons. Do not edit by hand. */",
    ".ri, .mdi, .bx, .bxs, .bxl { line-height: 1; }"
  ];

  if (iconSelector) blocks.push(renderSharedIconRule(iconSelector));
  for (const iconClass of iconClasses) {
    if (ICON_UTILITY_CLASSES.has(iconClass)) continue;
    blocks.push(renderIconRule(iconClass, renderIconDataUri(iconClass, resolveIcon(iconClass))));
  }
  if (iconClasses.has("mdi-spin")) blocks.push(renderMdiSpinUtility());
  return `${blocks.join("\n\n")}\n`;
}

function resolveIcon(iconClass) {
  const prefix = iconClass.split("-")[0];
  const setName = prefix === "bxs" || prefix === "bxl" ? "bx" : prefix;
  const iconName = toIconifyName(iconClass);
  const iconSet = iconSets[setName];
  if (!iconSet) throw new Error(`Unsupported icon prefix ${prefix}: ${iconClass}`);

  const icon = iconSet.icons[iconName];
  if (!icon) throw new Error(`Icon data does not exist: ${iconClass} -> ${setName}:${iconName}`);
  return {
    body: icon.body,
    height: icon.height ?? iconSet.height ?? 24,
    left: icon.left ?? iconSet.left ?? 0,
    top: icon.top ?? iconSet.top ?? 0,
    width: icon.width ?? iconSet.width ?? 24
  };
}

function toIconifyName(iconClass) {
  if (iconClass.startsWith("ri-")) return iconClass.slice(3);
  if (iconClass.startsWith("mdi-")) return iconClass.slice(4);
  if (iconClass.startsWith("bx-")) return iconClass.slice(3);
  return iconClass;
}

function renderIconDataUri(iconClass, icon) {
  const body = icon.body.replaceAll("currentColor", "#000");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${icon.left} ${icon.top} ${icon.width} ${icon.height}">${body}</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function renderSharedIconRule(iconSelector) {
  return `${iconSelector} {
  content: "";
  display: inline-block;
  width: 1em;
  height: 1em;
  vertical-align: -0.125em;
  background-color: currentColor;
  -webkit-mask: var(--om-icon) no-repeat center / contain;
  mask: var(--om-icon) no-repeat center / contain;
}`;
}

function renderIconRule(iconClass, dataUri) {
  return `.${iconClass}::before {
  --om-icon: url("${dataUri}");
}`;
}

function renderMdiSpinUtility() {
  return `.mdi-spin::before {
  animation: mdi-spin 2s infinite linear;
}

@keyframes mdi-spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(359deg); }
}`;
}
