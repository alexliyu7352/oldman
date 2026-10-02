import "./admin.css";
import { setupPage, type LanguageDefinition, type OldmanApp, type TranslationCatalog } from "oldman-web/core";
import { createDashboardCrudComponentLoaders, DashboardPage, startDashboard } from "oldman-web/dashboard";

interface AdminI18nBootstrap {
  catalog: TranslationCatalog;
  currentLanguage: string;
  defaultLanguage: string;
  languages: readonly LanguageDefinition[];
  preferencePath: string | null;
}

class AdminPage extends DashboardPage {
  constructor(root: HTMLElement) {
    const adminBasePath = readAdminBasePath();
    super({
      componentLoaders: createDashboardCrudComponentLoaders({
        autocomplete: async () => (await import("oldman-web/components/autocomplete")).Autocomplete,
        "date-time-picker": async () => (await import("oldman-web/components/date-time-picker")).DateTimePicker,
        dropdown: async () => (await import("oldman-web/components/dropdown")).Dropdown,
        feedback: async () => (await import("oldman-web/dashboard/feedback")).DashboardFeedback,
        form: async () => (await import("oldman-web/components/form")).Form,
        "form-validator": async () => (await import("oldman-web/components/form-validator")).FormValidator,
        "language-switcher": async () => (await import("oldman-web/components/language-switcher")).LanguageSwitcher,
        modal: async () => (await import("oldman-web/dashboard/modal")).DashboardModal,
        popover: async () => (await import("oldman-web/components/popover")).Popover,
        preloader: async () => (await import("oldman-web/components/preloader")).Preloader,
        select: async () => (await import("oldman-web/components/select")).Select,
        "table-filter-form": async () => (await import("oldman-web/components/table-filter-form")).TableFilterForm,
        tooltip: async () => (await import("oldman-web/components/tooltip")).Tooltip
      }),
      sidebarOptions: { defaultDashboardPath: adminBasePath },
      topbarOptions: { defaultNotificationHref: adminBasePath },
      root
    });
  }
}

setupPage("admin", AdminPage);

function startAdmin(): Promise<OldmanApp> {
  const i18nBootstrap = readAdminI18nBootstrap();
  return startDashboard({
    // Catalog paths are site-absolute ({prefix}/i18n/...); the asset base only serves the bundle's own files.
    assetBaseFallback: new URL(/* @vite-ignore */ "./", import.meta.url).toString(),
    // Any entry name the templates use that is not registered still mounts the Admin shell.
    fallbackPage: AdminPage,
    i18n: {
      defaultLanguage: i18nBootstrap.defaultLanguage,
      initialCatalog: { catalog: i18nBootstrap.catalog, language: i18nBootstrap.currentLanguage },
      languagePreferencePath: i18nBootstrap.preferencePath,
      languages: i18nBootstrap.languages
    }
  });
}

function readAdminBasePath(): string {
  return document.querySelector<HTMLMetaElement>('meta[name="oldman-admin-base"]')?.content || "/";
}

function readAdminI18nBootstrap(): AdminI18nBootstrap {
  const language = document.documentElement.lang || "en";
  const fallback: AdminI18nBootstrap = {
    catalog: { locale: language, messages: {} },
    currentLanguage: language,
    defaultLanguage: language,
    languages: [
      {
        aliases: [],
        catalogPath: "",
        code: language,
        flag: "",
        flagUrl: "",
        locale: language,
        name: language
      }
    ],
    // Without the server's bootstrap there is no endpoint to name: the choice stays in this browser.
    preferencePath: null
  };
  const source = document.querySelector<HTMLScriptElement>("#oldman-admin-i18n")?.textContent;
  if (!source) return fallback;

  try {
    const bootstrap = JSON.parse(source) as unknown;
    if (!isRecord(bootstrap) || !isTranslationCatalog(bootstrap.catalog)) return fallback;
    if (
      typeof bootstrap.currentLanguage !== "string"
      || typeof bootstrap.defaultLanguage !== "string"
      || typeof bootstrap.preferencePath !== "string"
      || !Array.isArray(bootstrap.languages)
      || !bootstrap.languages.length
      || !bootstrap.languages.every(isLanguageDefinition)
    ) {
      return fallback;
    }
    return {
      catalog: bootstrap.catalog,
      currentLanguage: bootstrap.currentLanguage,
      defaultLanguage: bootstrap.defaultLanguage,
      languages: bootstrap.languages,
      preferencePath: bootstrap.preferencePath
    };
  } catch {
    return fallback;
  }
}

function isTranslationCatalog(value: unknown): value is TranslationCatalog {
  return isRecord(value)
    && typeof value.locale === "string"
    && isTranslationMessages(value.messages)
    && (value.pluralRule === undefined || typeof value.pluralRule === "string");
}

function isTranslationMessages(value: unknown): value is TranslationCatalog["messages"] {
  if (!isRecord(value)) return false;
  return Object.values(value).every((message) => {
    return typeof message === "string" || (Array.isArray(message) && message.every((item) => typeof item === "string"));
  });
}

function isLanguageDefinition(value: unknown): value is LanguageDefinition {
  return isRecord(value)
    && typeof value.code === "string"
    && typeof value.locale === "string"
    && Array.isArray(value.aliases)
    && value.aliases.every((alias) => typeof alias === "string")
    && typeof value.flag === "string"
    && (value.flagUrl === undefined || typeof value.flagUrl === "string")
    && typeof value.catalogPath === "string"
    && typeof value.name === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

void startAdmin().catch((error: unknown) => {
  console.error("Oldman Admin startup failed", error);
});
