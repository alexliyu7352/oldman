import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import oldmanWebPackage from "oldman-web/package.json";
import { oldmanWebAliases } from "../../../vite.oldman-web";

type PackageExport = string | { import: string; types: string };

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../packages/oldman-web");

function publicSpecifier(exportName: string): string {
  return exportName === "." ? "oldman-web" : `oldman-web/${exportName.replace(/^\.\//, "")}`;
}

function sourceTarget(exportName: string, metadata: PackageExport): string {
  if (exportName === "./package.json") return resolve(packageRoot, "package.json");
  const publishedTarget = typeof metadata === "string" ? metadata : metadata.import;
  const sourceTarget = publishedTarget.replace(/^\.\/dist\//, "src/").replace(/\.js$/, ".ts");
  return resolve(packageRoot, sourceTarget);
}

function matchingAliases(specifier: string): ReturnType<typeof oldmanWebAliases> {
  return oldmanWebAliases().filter(({ find }) => {
    if (typeof find === "string") return specifier === find || specifier.startsWith(`${find}/`);
    find.lastIndex = 0;
    return find.test(specifier);
  });
}

describe("oldman-web workspace package metadata", () => {
  it("resolves the published package.json export in Vite and TypeScript", () => {
    expect(oldmanWebPackage.name).toBe("oldman-web");
    expect(oldmanWebPackage.version).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("keeps Vite source aliases exactly aligned with published exports", () => {
    const exports = oldmanWebPackage.exports as Record<string, PackageExport>;

    for (const [exportName, metadata] of Object.entries(exports)) {
      const specifier = publicSpecifier(exportName);
      expect(matchingAliases(specifier), specifier).toEqual([
        expect.objectContaining({ replacement: sourceTarget(exportName, metadata) })
      ]);
      expect(matchingAliases(`${specifier}/private`), `${specifier}/private`).toEqual([]);
    }
  });

  it("rejects representative workspace-private source paths", () => {
    for (const specifier of [
      "oldman-web/core/page/page",
      "oldman-web/components/loaders",
      "oldman-web/dashboard/sidebar",
      "oldman-web/package.json/private"
    ]) {
      expect(matchingAliases(specifier), specifier).toEqual([]);
    }
  });
});
