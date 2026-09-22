import { beforeEach, describe, expect, it, vi } from "vitest";
import { contextKey, createI18n, loadCatalogForLocale, loadI18nCatalog, localeCandidates } from "./i18n";

describe("createI18n", () => {
  beforeEach(() => {
    document.documentElement.lang = "en";
    document.body.innerHTML = "";
    localStorage.clear();
    document.cookie = "preferred_language=; path=/; max-age=0";
    document.cookie = "lang=; path=/; max-age=0";
    vi.restoreAllMocks();
  });

  it("translates messages and falls back to the key", () => {
    const i18n = createI18n({
      locale: "zh-CN",
      messages: {
        "Hello": "你好"
      }
    });

    expect(i18n.t("Hello")).toBe("你好");
    expect(i18n.t("Missing")).toBe("Missing");
  });

  it("interpolates named variables", () => {
    const i18n = createI18n({
      locale: "en",
      messages: {
        "Hello, {name}": "Hello, {name}"
      }
    });

    expect(i18n.t("Hello, {name}", { name: "Alex" })).toBe("Hello, Alex");
  });

  it("selects plural forms using catalog plural rules", () => {
    const i18n = createI18n({
      locale: "en",
      pluralRule: "n != 1",
      messages: {
        "{count} file": ["{count} file", "{count} files"]
      }
    });

    expect(i18n.tn("{count} file", "{count} files", 1, { count: 1 })).toBe("1 file");
    expect(i18n.tn("{count} file", "{count} files", 3, { count: 3 })).toBe("3 files");
  });

  it("selects plural forms using multi-branch gettext rules", () => {
    const i18n = createI18n({
      locale: "ru",
      pluralRule: "n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2",
      messages: {
        "{count} file": ["{count} файл", "{count} файла", "{count} файлов"]
      }
    });

    expect(i18n.tn("{count} file", "{count} files", 1)).toBe("1 файл");
    expect(i18n.tn("{count} file", "{count} files", 2)).toBe("2 файла");
    expect(i18n.tn("{count} file", "{count} files", 5)).toBe("5 файлов");
  });

  it("falls back per plural index for sparse or empty runtime catalogs", () => {
    const sparseForms = new Array<string>(3);
    sparseForms[2] = "{count} fichiers";
    const i18n = createI18n({
      locale: "fr",
      pluralRule: "n == 1 ? 0 : n == 2 ? 1 : 2",
      messages: {
        "{count} file": sparseForms,
        [contextKey("upload", "{count} file")]: [
          "",
          "",
          "{count} fichiers envoyes"
        ]
      }
    });

    expect(i18n.tn("{count} file", "{count} files", 1)).toBe("1 file");
    expect(i18n.tn("{count} file", "{count} files", 2)).toBe("2 files");
    expect(i18n.tn("{count} file", "{count} files", 3)).toBe("3 fichiers");
    expect(
      i18n.tnc("upload", "{count} file", "{count} files", 1)
    ).toBe("1 file");
    expect(
      i18n.tnc("upload", "{count} file", "{count} files", 2)
    ).toBe("2 files");
    expect(
      i18n.tnc("upload", "{count} file", "{count} files", 3)
    ).toBe("3 fichiers envoyes");
  });

  it("can switch catalogs at runtime", () => {
    const i18n = createI18n({
      locale: "en",
      messages: {
        "Save": "Save"
      }
    });

    i18n.setCatalog({
      locale: "zh-CN",
      messages: {
        "Save": "保存"
      }
    });

    expect(i18n.locale).toBe("zh-CN");
    expect(i18n.t("Save")).toBe("保存");
  });

  it("translates context-specific messages", () => {
    const i18n = createI18n({
      locale: "zh-CN",
      messages: {
        [contextKey("verb", "Open")]: "打开",
        [contextKey("status", "Open")]: "开放"
      }
    });

    expect(i18n.tc("verb", "Open")).toBe("打开");
    expect(i18n.tc("status", "Open")).toBe("开放");
    expect(i18n.tc("missing", "Open")).toBe("Open");
  });

  it("translates context-specific plural messages", () => {
    const i18n = createI18n({
      locale: "fr",
      pluralRule: "n > 1",
      messages: {
        [contextKey("upload", "{count} file")]: ["{count} fichier envoye", "{count} fichiers envoyes"]
      }
    });

    expect(i18n.tnc("upload", "{count} file", "{count} files", 1)).toBe("1 fichier envoye");
    expect(i18n.tnc("upload", "{count} file", "{count} files", 2)).toBe("2 fichiers envoyes");
    expect(i18n.tnc("download", "{count} file", "{count} files", 2)).toBe("2 files");
  });

  it("builds locale fallback candidates for generated gettext catalogs", () => {
    expect(localeCandidates("zh-CN")).toEqual(["zh-CN", "zh_CN", "zh"]);
    expect(localeCandidates("pt_BR")).toEqual(["pt_BR", "pt-BR", "pt"]);
    expect(localeCandidates("  ")).toEqual([]);
  });

  it("loads the first available catalog from locale candidates", async () => {
    const requested: string[] = [];

    const catalog = await loadCatalogForLocale("zh-CN", async (locale) => {
      requested.push(locale);
      return locale === "zh_CN"
        ? {
            locale,
            messages: {
              Save: "保存"
            }
          }
        : null;
    });

    expect(requested).toEqual(["zh-CN", "zh_CN"]);
    expect(catalog?.messages.Save).toBe("保存");
  });

  it("installs a loaded catalog into an existing runtime", async () => {
    const i18n = createI18n({
      locale: "en",
      messages: {
        Save: "Save"
      }
    });

    await loadI18nCatalog(i18n, "zh-CN", async (locale) => ({
      locale,
      messages: {
        Save: "保存"
      }
    }));

    expect(i18n.locale).toBe("zh-CN");
    expect(i18n.t("Save")).toBe("保存");
  });

  it("initializes from cookie when local storage has no language", async () => {
    document.cookie = "preferred_language=zh-hans; path=/";
    document.documentElement.lang = "en";
    const i18n = createI18n({
      defaultLanguage: "en",
      languages: [
        { code: "en", locale: "en", aliases: [], flag: "", catalogPath: "i18n/en.json", name: "English" },
        {
          code: "zh-hans",
          locale: "zh_Hans",
          aliases: ["zh_CN"],
          flag: "",
          catalogPath: "i18n/zh-hans.json",
          name: "简体中文"
        }
      ],
      aliases: { en: "en", "zh-hans": "zh-hans", zh_CN: "zh-hans" },
      document,
      catalogLoader: async (language) => ({
        locale: language.locale,
        messages: language.code === "zh-hans" ? { Save: "保存" } : {}
      })
    });

    await i18n.init();

    expect(i18n.currentLanguage).toBe("zh-hans");
    expect(document.documentElement.lang).toBe("zh-hans");
    expect(i18n.t("Save")).toBe("保存");
  });

  it("loads only the target catalog when language changes", async () => {
    const loaded: string[] = [];
    const i18n = createI18n({
      defaultLanguage: "en",
      languages: [
        { code: "en", locale: "en", aliases: [], flag: "", catalogPath: "i18n/en.json", name: "English" },
        {
          code: "zh-hans",
          locale: "zh_Hans",
          aliases: [],
          flag: "",
          catalogPath: "i18n/zh-hans.json",
          name: "简体中文"
        }
      ],
      aliases: { en: "en", "zh-hans": "zh-hans" },
      document,
      catalogLoader: async (language) => {
        loaded.push(language.code);
        return { locale: language.locale, messages: {} };
      }
    });

    await i18n.setLanguage("zh-hans", { persist: false, syncBackend: false });

    expect(loaded).toEqual(["zh-hans"]);
    expect(i18n.currentLanguage).toBe("zh-hans");
  });

  it("waits for backend preference synchronization before resolving", async () => {
    let releaseBackend!: () => void;
    const backendPending = new Promise<void>((resolve) => {
      releaseBackend = resolve;
    });
    let backendCalls = 0;
    const http = {
      async postJson<T>(): Promise<T> {
        backendCalls += 1;
        await backendPending;
        return {} as T;
      }
    };
    const i18n = createI18n({
      catalogLoader: async (language) => ({ locale: language.locale, messages: {} }),
      defaultLanguage: "en",
      document,
      http,
      initialCatalog: { locale: "en", messages: {} },
      languagePreferencePath: "/control/preferences/language",
      languages: [
        { aliases: [], catalogPath: "", code: "en", flag: "", locale: "en", name: "English" },
        { aliases: [], catalogPath: "", code: "zh-Hans", flag: "", locale: "zh-Hans", name: "简体中文" }
      ]
    });
    let settled = false;

    const changing = i18n.setLanguage("zh-Hans", { persist: false }).then((language) => {
      settled = true;
      return language;
    });
    await vi.waitFor(() => expect(backendCalls).toBe(1));

    expect(settled).toBe(false);
    releaseBackend();
    await expect(changing).resolves.toBe("zh-Hans");
    expect(settled).toBe(true);
  });

  it("keeps the latest selection when catalogs resolve out of order", async () => {
    const catalogResolvers = new Map<string, (catalog: { locale: string; messages: Record<string, string> }) => void>();
    const i18n = createI18n({
      catalogLoader: (language) => new Promise((resolve) => catalogResolvers.set(language.code, resolve)),
      defaultLanguage: "en",
      document,
      initialCatalog: { locale: "en", messages: { Save: "Save" } },
      languages: [
        { aliases: [], catalogPath: "", code: "en", flag: "", locale: "en", name: "English" },
        { aliases: [], catalogPath: "", code: "zh-Hans", flag: "", locale: "zh-Hans", name: "简体中文" },
        { aliases: [], catalogPath: "", code: "zh-Hant", flag: "", locale: "zh-Hant", name: "繁體中文" }
      ]
    });

    const first = i18n.setLanguage("zh-Hans", { persist: false, syncBackend: false });
    const second = i18n.setLanguage("zh-Hant", { persist: false, syncBackend: false });
    catalogResolvers.get("zh-Hant")?.({ locale: "zh-Hant", messages: { Save: "儲存" } });
    await second;
    catalogResolvers.get("zh-Hans")?.({ locale: "zh-Hans", messages: { Save: "保存" } });
    await first;

    expect(i18n.currentLanguage).toBe("zh-Hant");
    expect(document.documentElement.lang).toBe("zh-Hant");
    expect(i18n.t("Save")).toBe("儲存");
  });
});

describe("translateDocument owns a namespaced attribute", () => {
  it("translates [data-om-i18n-key] and leaves business [data-key] alone", () => {
    // 框架有 296 个 data-om-* 属性,translateDocument 原先用的是裸 data-key ——
    // 而它会覆写 textContent,所以一张用 data-key 存行主键的表格会在切语言时被写成主键本身。
    document.body.innerHTML = `
      <p data-om-i18n-key="Loading...">Loading...</p>
      <table><tbody><tr><td data-key="row-42">Alice</td></tr></tbody></table>
    `;
    createI18n({ locale: "fr", messages: { "Loading...": "Chargement..." } }).translateDocument(document);

    expect(document.querySelector("[data-om-i18n-key]")?.textContent).toBe("Chargement...");
    expect(document.querySelector("[data-key]")?.textContent).toBe("Alice");
  });
});
