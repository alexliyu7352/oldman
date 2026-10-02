import {
  createFetchCatalogLoader,
  createHttpClient,
  createI18n,
  createOldmanContext,
  readAssetBaseUrl,
  setOldmanContext,
  startOldman,
  type HttpClientOptions,
  type LanguageDefinition,
  type OldmanApp,
  type PageConstructor,
  type PageLoader,
  type TranslationCatalog
} from "../core/index";
import { AuthPage } from "./auth-page";

/** The `data-om-page` name the framework's auth base template gives its pages. */
export const AUTH_PAGE_NAME = "login";

export interface DashboardI18nOptions {
  languages: readonly LanguageDefinition[];
  defaultLanguage: string;
  aliases?: Record<string, string>;
  /**
   * Where a language choice is posted: `i18n.preference_url`, carried by the generated manifest or the
   * Admin's page. `null` keeps the choice in this browser (cookie and storage) only.
   */
  languagePreferencePath: string | null;
  /** A catalog the page already carries, for `language`; the other languages' catalogs are fetched. */
  initialCatalog?: { language: string; catalog: TranslationCatalog };
}

export interface StartDashboardOptions {
  /** The language contract: a project's generated manifest, or the one the Admin embeds in its page. */
  i18n: DashboardI18nOptions;
  /** Where bundle assets resolve when the page carries no `oldman-asset-base` meta. */
  assetBaseFallback?: string;
  /** Page class for entry names nothing else registered. */
  fallbackPage?: PageConstructor;
  /** Loads a page entry the first time a page names it, such as a project's `import.meta.glob` of its pages. */
  pageLoader?: PageLoader;
  /** Page class for the auth pages; the framework's `AuthPage` unless the host brings its own. */
  authPage?: PageConstructor;
}

let started: Promise<OldmanApp> | null = null;

/**
 * Start the Oldman runtime for a dashboard or the built-in Admin: HTTP client, i18n, context, page
 * lifecycle. Calling it again returns the same application; a start that failed may be tried again.
 *
 * A request that answers 401 sends the browser to the login page the server names in the answer.
 */
export function startDashboard(options: StartDashboardOptions): Promise<OldmanApp> {
  if (!started) {
    started = launch(options).catch((error: unknown) => {
      started = null;
      throw error;
    });
  }
  return started;
}

/** Stop the application `startDashboard` started, for tests and full-page teardown. */
export async function stopDashboard(): Promise<void> {
  if (!started) return;
  const app = await started;
  await app.destroy();
  started = null;
  delete document.documentElement.dataset.omReady;
}

async function launch(options: StartDashboardOptions): Promise<OldmanApp> {
  const httpOptions: HttpClientOptions = { onAuthRedirect: (url) => window.location.assign(url) };
  const http = createHttpClient(httpOptions);
  const assetBaseUrl = readAssetBaseUrl(options.assetBaseFallback ? { fallback: options.assetBaseFallback } : {});
  const { aliases, defaultLanguage, initialCatalog, languagePreferencePath, languages } = options.i18n;
  const i18n = createI18n({
    ...(aliases ? { aliases } : {}),
    catalogLoader: createFetchCatalogLoader({
      assetBaseUrl,
      ...(initialCatalog ? { initialCatalog: initialCatalog.catalog, initialLanguage: initialCatalog.language } : {})
    }),
    defaultLanguage,
    document,
    http,
    ...(initialCatalog ? { initialCatalog: initialCatalog.catalog } : {}),
    languagePreferencePath,
    languages
  });
  const context = createOldmanContext({ assetBaseUrl, document, http, httpOptions, i18n });
  setOldmanContext(context);
  await context.i18n.init();
  context.pageRegistry.register(AUTH_PAGE_NAME, options.authPage ?? AuthPage);
  const app = await startOldman({
    context,
    ...(options.pageLoader ? { pageLoader: options.pageLoader } : {}),
    ...(options.fallbackPage ? { fallbackPage: options.fallbackPage } : {})
  });
  document.documentElement.dataset.omReady = "true";
  return app;
}
