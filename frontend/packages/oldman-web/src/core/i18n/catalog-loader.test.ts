import { beforeEach, describe, expect, it, vi } from "vitest";

import { createFetchCatalogLoader, readAssetBaseUrl } from "./catalog-loader";
import type { LanguageDefinition } from "./i18n";

const language: LanguageDefinition = {
  code: "zh_Hans",
  locale: "zh_Hans",
  aliases: [],
  flag: "",
  catalogPath: "/i18n/zh_Hans.json",
  name: "简体中文"
};

describe("readAssetBaseUrl", () => {
  beforeEach(() => {
    document.head.innerHTML = "";
  });

  it("resolves the declared meta against the current address", () => {
    document.head.innerHTML = '<meta name="oldman-asset-base" content="/static/dist/">';

    expect(readAssetBaseUrl()).toBe(`${window.location.origin}/static/dist/`);
  });

  it("keeps an absolute dev server address", () => {
    document.head.innerHTML = '<meta name="oldman-asset-base" content="http://localhost:5173/">';

    expect(readAssetBaseUrl()).toBe("http://localhost:5173/");
  });

  it("falls back to the site root, or to the caller's own fallback", () => {
    expect(readAssetBaseUrl()).toBe(`${window.location.origin}/`);
    expect(readAssetBaseUrl({ fallback: "http://cdn.example.test/assets/" })).toBe("http://cdn.example.test/assets/");
  });
});

describe("createFetchCatalogLoader", () => {
  it("fetches the catalog under the asset base", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ locale: "zh_Hans", messages: { Save: "保存" } })
    });
    const loader = createFetchCatalogLoader({ assetBaseUrl: "http://localhost:5173/", fetchImpl: fetchImpl as unknown as typeof fetch });

    const catalog = await loader(language);

    expect(fetchImpl).toHaveBeenCalledWith("http://localhost:5173/i18n/zh_Hans.json", { headers: { Accept: "application/json" } });
    expect(catalog).toEqual({ locale: "zh_Hans", messages: { Save: "保存" } });
  });

  it("keeps a site-absolute catalog path on a page below the site root", async () => {
    // Admin 的语言包是挂在它前缀下的路由，和 bundle 不同挂载点，所以它不传 assetBaseUrl。
    window.history.pushState({}, "", "/admin/auth/user/");
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ locale: "zh_Hans", messages: {} })
    });
    const loader = createFetchCatalogLoader({ fetchImpl: fetchImpl as unknown as typeof fetch });

    await loader({ ...language, catalogPath: "/admin/i18n/zh_Hans.json" });

    expect(fetchImpl).toHaveBeenCalledWith(`${window.location.origin}/admin/i18n/zh_Hans.json`, {
      headers: { Accept: "application/json" }
    });
    window.history.pushState({}, "", "/");
  });

  it("returns the inlined catalog for the current language without a request", async () => {
    const fetchImpl = vi.fn();
    const initialCatalog = { locale: "zh_Hans", messages: { Save: "保存" } };
    const loader = createFetchCatalogLoader({
      initialCatalog,
      initialLanguage: "zh_Hans",
      fetchImpl: fetchImpl as unknown as typeof fetch
    });

    expect(await loader(language)).toBe(initialCatalog);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("answers an empty catalog for a failed request, junk content or a language without a path", async () => {
    const failing = createFetchCatalogLoader({ fetchImpl: (() => Promise.resolve({ ok: false })) as unknown as typeof fetch });
    const junk = createFetchCatalogLoader({
      fetchImpl: (() => Promise.resolve({ ok: true, json: () => Promise.resolve("not a catalog") })) as unknown as typeof fetch
    });
    const throwing = createFetchCatalogLoader({ fetchImpl: (() => Promise.reject(new Error("offline"))) as unknown as typeof fetch });
    const pathless = createFetchCatalogLoader({});

    expect(await failing(language)).toEqual({ locale: "zh_Hans", messages: {} });
    expect(await junk(language)).toEqual({ locale: "zh_Hans", messages: {} });
    expect(await throwing(language)).toEqual({ locale: "zh_Hans", messages: {} });
    expect(await pathless({ ...language, catalogPath: "" })).toEqual({ locale: "zh_Hans", messages: {} });
  });
});
