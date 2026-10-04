import { afterEach, describe, expect, it, vi } from "vitest";
import { Page } from "../core/page/page";
import { getOldmanContext, resetOldmanContext } from "../core/runtime/context";
import { AuthPage } from "./auth-page";
import { AUTH_PAGE_NAME, startDashboard, stopDashboard, type DashboardI18nOptions } from "./start";

const i18n: DashboardI18nOptions = {
  defaultLanguage: "en",
  languagePreferencePath: "/account/language",
  languages: [{ aliases: [], catalogPath: "", code: "en", flag: "", locale: "en", name: "English" }]
};

class HostLoginPage extends Page {}

describe("startDashboard", () => {
  afterEach(async () => {
    await stopDashboard();
    resetOldmanContext();
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("mounts the framework's auth page on the auth base and returns one application however often it is called", async () => {
    document.body.innerHTML = `<main data-om-page="${AUTH_PAGE_NAME}"></main>`;

    const first = startDashboard({ i18n });
    expect(startDashboard({ i18n })).toBe(first);
    await first;

    expect(getOldmanContext().pageRegistry.current).toBeInstanceOf(AuthPage);
    expect(document.documentElement.dataset.omReady).toBe("true");

    await stopDashboard();
    expect(document.documentElement.dataset.omReady).toBeUndefined();
    expect(getOldmanContext().pageRegistry.current).toBeNull();
  });

  it("lets the host bring its own auth page", async () => {
    document.body.innerHTML = `<main data-om-page="${AUTH_PAGE_NAME}"></main>`;

    await startDashboard({ authPage: HostLoginPage, i18n });

    expect(getOldmanContext().pageRegistry.current).toBeInstanceOf(HostLoginPage);
  });

  it("can be tried again after a start that failed", async () => {
    document.body.innerHTML = `<main data-om-page="${AUTH_PAGE_NAME}"></main>`;
    const badAssetBase = document.createElement("meta");
    badAssetBase.name = "oldman-asset-base";
    badAssetBase.content = "http://[";
    document.head.append(badAssetBase);

    await expect(startDashboard({ i18n })).rejects.toBeInstanceOf(TypeError);

    badAssetBase.remove();
    await expect(startDashboard({ i18n })).resolves.toBeDefined();
    expect(document.documentElement.dataset.omReady).toBe("true");
  });

  it("loads the language catalog from under the page's asset base, a relative one resolved against the page", async () => {
    document.body.innerHTML = `<main data-om-page="${AUTH_PAGE_NAME}"></main>`;
    const assetBase = document.createElement("meta");
    assetBase.name = "oldman-asset-base";
    assetBase.content = "/static/dist/";
    document.head.append(assetBase);
    const fetch = vi.fn(async () => new Response(JSON.stringify({ locale: "en", messages: {} }), { headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    try {
      await startDashboard({ i18n: { ...i18n, languages: [{ ...i18n.languages[0]!, catalogPath: "i18n/en.json" }] } });

      expect(fetch).toHaveBeenCalledWith(new URL("/static/dist/i18n/en.json", window.location.href).toString(), expect.any(Object));
    } finally {
      assetBase.remove();
      vi.unstubAllGlobals();
    }
  });

  it("posts language choices to the endpoint the language contract names", async () => {
    document.body.innerHTML = `<main data-om-page="${AUTH_PAGE_NAME}"></main>`;
    await startDashboard({ i18n });
    const context = getOldmanContext();
    const post = vi.spyOn(context.http, "postJson").mockResolvedValue({});

    await context.i18n.setLanguage("en", { syncBackend: true });

    expect(post).toHaveBeenCalledWith("/account/language", { language: "en" });
  });
});
