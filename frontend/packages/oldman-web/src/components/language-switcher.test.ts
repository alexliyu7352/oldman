import { afterEach, describe, expect, it } from "vitest";
import {
  createI18n,
  createOldmanContext,
  resetOldmanContext,
  setOldmanContext
} from "../core/index";
import { Dropdown } from "./dropdown";
import { LanguageSwitcher } from "./language-switcher";

describe("LanguageSwitcher", () => {
  afterEach(() => {
    resetOldmanContext();
    document.body.replaceChildren();
    window.history.replaceState(null, "", "/");
  });

  it("hides the current flag when the language has no configured image", async () => {
    document.body.innerHTML = `
      <div data-om-component="language-switcher">
        <button class="oldman-language-button" data-om-language-current>
          <img src="/stale.svg" data-om-language-current-flag>
          <span data-om-language-current-name hidden></span>
        </button>
        <button type="button" data-lang="en"></button>
      </div>
    `;
    const i18n = createI18n({
      defaultLanguage: "en",
      document,
      initialCatalog: { locale: "en", messages: {} },
      languages: [
        {
          aliases: [],
          catalogPath: "",
          code: "en",
          flag: "",
          flagUrl: "",
          locale: "en",
          name: "English"
        }
      ]
    });
    setOldmanContext(
      createOldmanContext({
        assetBaseUrl: "https://example.test/static/",
        document,
        i18n
      })
    );
    const root = document.querySelector<HTMLElement>(
      '[data-om-component="language-switcher"]'
    )!;
    const switcher = new LanguageSwitcher(root);

    await switcher.start();

    const flag = root.querySelector<HTMLImageElement>(
      "[data-om-language-current-flag]"
    )!;
    expect(flag.hidden).toBe(true);
    expect(flag.hasAttribute("src")).toBe(false);
    expect(flag.alt).toBe("English");
    const name = root.querySelector<HTMLElement>(
      "[data-om-language-current-name]"
    )!;
    expect(name.textContent).toBe("English");
    expect(name.hidden).toBe(false);
    expect(
      root.querySelector("[data-om-language-current]")
        ?.classList.contains("has-language-name")
    ).toBe(true);

    await switcher.stop();
  });

  it("closes the containing dropdown after a language is selected", async () => {
    document.body.innerHTML = `
      <div data-om-component="dropdown">
        <div data-om-component="language-switcher">
          <button type="button" data-om-dropdown-toggle aria-expanded="true"></button>
          <div class="om-dropdown-menu show" data-om-dropdown-menu>
            <button type="button" data-lang="zh-Hans">简体中文</button>
          </div>
        </div>
      </div>
    `;
    const i18n = createI18n({
      catalogLoader: async (language) => ({ locale: language.locale, messages: {} }),
      defaultLanguage: "en",
      document,
      initialCatalog: { locale: "en", messages: {} },
      languages: [
        { aliases: [], catalogPath: "", code: "en", flag: "", locale: "en", name: "English" },
        { aliases: [], catalogPath: "", code: "zh-Hans", flag: "", locale: "zh-Hans", name: "简体中文" }
      ]
    });
    setOldmanContext(createOldmanContext({ document, i18n }));
    const dropdownRoot = document.querySelector<HTMLElement>('[data-om-component="dropdown"]')!;
    const switcherRoot = document.querySelector<HTMLElement>('[data-om-component="language-switcher"]')!;
    const dropdown = new Dropdown(dropdownRoot);
    const switcher = new LanguageSwitcher(switcherRoot);

    await dropdown.start();
    await switcher.start();
    switcherRoot.querySelector<HTMLElement>('[data-lang="zh-Hans"]')!.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const menu = dropdownRoot.querySelector<HTMLElement>("[data-om-dropdown-menu]")!;
    expect(menu.hidden).toBe(true);
    expect(menu.classList.contains("hidden")).toBe(true);
    expect(menu.classList.contains("show")).toBe(false);
    expect(dropdownRoot.querySelector("[data-om-dropdown-toggle]")?.getAttribute("aria-expanded")).toBe("false");

    await switcher.stop();
    await dropdown.stop();
  });

  it("navigates to the server-provided URL after selecting a new language", async () => {
    document.body.innerHTML = `
      <div data-om-component="language-switcher">
        <button type="button" data-lang="zh-Hans" data-om-language-url="#zh-Hans">简体中文</button>
      </div>
    `;
    const i18n = createI18n({
      catalogLoader: async (language) => ({ locale: language.locale, messages: {} }),
      defaultLanguage: "en",
      document,
      initialCatalog: { locale: "en", messages: {} },
      languages: [
        { aliases: [], catalogPath: "", code: "en", flag: "", locale: "en", name: "English" },
        { aliases: [], catalogPath: "", code: "zh-Hans", flag: "", locale: "zh-Hans", name: "简体中文" }
      ]
    });
    setOldmanContext(createOldmanContext({ document, i18n }));
    const root = document.querySelector<HTMLElement>('[data-om-component="language-switcher"]')!;
    const switcher = new LanguageSwitcher(root);

    await switcher.start();
    root.querySelector<HTMLElement>('[data-lang="zh-Hans"]')!.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(window.location.hash).toBe("#zh-Hans");
    await switcher.stop();
  });

  it("does not navigate for an older selection that finishes last", async () => {
    document.body.innerHTML = `
      <div data-om-component="language-switcher">
        <button type="button" data-lang="zh-Hans" data-om-language-url="#zh-Hans">简体中文</button>
        <button type="button" data-lang="zh-Hant" data-om-language-url="#zh-Hant">繁體中文</button>
      </div>
    `;
    const catalogResolvers = new Map<string, (catalog: { locale: string; messages: Record<string, string> }) => void>();
    const i18n = createI18n({
      catalogLoader: (language) => new Promise((resolve) => catalogResolvers.set(language.code, resolve)),
      defaultLanguage: "en",
      document,
      initialCatalog: { locale: "en", messages: {} },
      languages: [
        { aliases: [], catalogPath: "", code: "en", flag: "", locale: "en", name: "English" },
        { aliases: [], catalogPath: "", code: "zh-Hans", flag: "", locale: "zh-Hans", name: "简体中文" },
        { aliases: [], catalogPath: "", code: "zh-Hant", flag: "", locale: "zh-Hant", name: "繁體中文" }
      ]
    });
    setOldmanContext(createOldmanContext({ document, i18n }));
    const root = document.querySelector<HTMLElement>('[data-om-component="language-switcher"]')!;
    const switcher = new LanguageSwitcher(root);

    await switcher.start();
    root.querySelector<HTMLElement>('[data-lang="zh-Hans"]')!.click();
    root.querySelector<HTMLElement>('[data-lang="zh-Hant"]')!.click();
    catalogResolvers.get("zh-Hant")?.({ locale: "zh-Hant", messages: {} });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(window.location.hash).toBe("#zh-Hant");

    catalogResolvers.get("zh-Hans")?.({ locale: "zh-Hans", messages: {} });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(window.location.hash).toBe("#zh-Hant");
    await switcher.stop();
  });
});
