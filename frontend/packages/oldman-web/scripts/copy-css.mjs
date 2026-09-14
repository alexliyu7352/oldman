import { mkdir, copyFile, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const componentSourceDir = resolve(root, "src/components");
const componentTargetDir = resolve(root, "dist/components");

for (const name of ["tailwind.css", "icons.css"]) {
  const source = resolve(root, "src/styles", name);
  const target = resolve(root, "dist/styles", name);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(source, target);
}

await mkdir(componentTargetDir, { recursive: true });
for (const entry of await readdir(componentSourceDir)) {
  if (!entry.endsWith(".scss")) continue;
  await copyFile(join(componentSourceDir, entry), join(componentTargetDir, entry));
}

await copyScssTree(resolve(root, "src/styles"), resolve(root, "dist/styles"));
await embedDeclarationMapSources(resolve(root, "dist"));

async function copyScssTree(sourceDir, targetDir) {
  await mkdir(targetDir, { recursive: true });
  for (const entry of await readdir(sourceDir)) {
    const sourcePath = join(sourceDir, entry);
    const targetPath = join(targetDir, entry);
    const entryStat = await stat(sourcePath);
    if (entryStat.isDirectory()) {
      await copyScssTree(sourcePath, targetPath);
      continue;
    }
    if (entry.endsWith(".scss")) {
      await copyFile(sourcePath, targetPath);
    }
  }
}

async function embedDeclarationMapSources(directory) {
  for (const entry of await readdir(directory)) {
    const entryPath = join(directory, entry);
    const entryStat = await stat(entryPath);
    if (entryStat.isDirectory()) {
      await embedDeclarationMapSources(entryPath);
      continue;
    }
    if (!entry.endsWith(".d.ts.map")) continue;

    const sourceMap = JSON.parse(await readFile(entryPath, "utf8"));
    const sourceRoot = sourceMap.sourceRoot || "";
    sourceMap.sourcesContent = await Promise.all(
      sourceMap.sources.map((source) => readFile(resolve(dirname(entryPath), sourceRoot, source), "utf8"))
    );
    await writeFile(entryPath, JSON.stringify(sourceMap));
  }
}
