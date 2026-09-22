import "./admin.css";
import {
  createFetchCatalogLoader,
  createHttpClient,
  createI18n,
  createOldmanContext,
  escapeHtml,
  getOldmanContext,
  readAssetBaseUrl,
  setOldmanContext,
  setupPage,
  startOldman,
  type LanguageDefinition,
  type TranslationCatalog
} from "oldman-web/core";
import { createDashboardCrudComponentLoaders, DashboardPage } from "oldman-web/dashboard";

interface AdminI18nBootstrap {
  catalog: TranslationCatalog;
  currentLanguage: string;
  defaultLanguage: string;
  languages: readonly LanguageDefinition[];
  preferencePath: string;
}

function adminNotificationEmptyState(): string {
  const message = escapeHtml(getOldmanContext().i18n.t("No notifications"));
  return `
    <div class="empty-notification-elem om-empty om-empty-sm">
      <p class="om-empty-description">${message}</p>
    </div>
  `;
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
      topbarOptions: {
        defaultNotificationHref: adminBasePath,
        emptyNotificationTemplate: adminNotificationEmptyState
      },
      root
    });
  }
}

setupPage("admin", AdminPage);

async function startAdmin(): Promise<void> {
  const authLoginPath = `${readAdminBasePath().replace(/\/+$/, "")}/login`;
  const httpOptions = {
    authLoginPath,
    onAuthRedirect: (url: string) => window.location.assign(url)
  };
  const http = createHttpClient(httpOptions);
  const i18nBootstrap = readAdminI18nBootstrap();
  const i18n = createI18n({
    // 目录路径相对站点根，不相对 bundle 目录，所以这里不传 assetBaseUrl。
    catalogLoader: createFetchCatalogLoader({
      initialCatalog: i18nBootstrap.catalog,
      initialLanguage: i18nBootstrap.currentLanguage
    }),
    defaultLanguage: i18nBootstrap.defaultLanguage,
    document,
    http,
    initialCatalog: i18nBootstrap.catalog,
    languagePreferencePath: i18nBootstrap.preferencePath,
    languages: i18nBootstrap.languages
  });
  const context = createOldmanContext({
    assetBaseUrl: readAssetBaseUrl({ fallback: new URL(/* @vite-ignore */ "./", import.meta.url).toString() }),
    document,
    http,
    httpOptions,
    i18n
  });
  setOldmanContext(context);
  await context.i18n.init();
  // Any entry name the templates use that is not registered still mounts the Admin shell.
  await startOldman({ context, fallbackPage: AdminPage });
  document.documentElement.dataset.omReady = "true";
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
    preferencePath: `${readAdminBasePath().replace(/\/+$/, "")}/preferences/language`
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
