import "./app.css";
import {
  createHttpClient,
  createI18n,
  createOldmanContext,
  setOldmanContext,
  startOldman,
  type LanguageDefinition,
  type TranslationCatalog,
  type OldmanApp
} from "oldman-web/core";

interface LanguageManifest {
  readonly defaultLanguage: string;
  readonly languages: readonly LanguageDefinition[];
}

const pageEntries = import.meta.glob("./pages/*.ts");
let appPromise: Promise<OldmanApp> | null = null;

export async function startDashboard(): Promise<OldmanApp> {
  if (appPromise) return appPromise;

  appPromise = (async () => {
    const http = createHttpClient({});
    const assetBaseUrl = readAssetBaseUrl();
    const manifest = await loadLanguageManifest(assetBaseUrl);
    const i18n = createI18n({
      catalogLoader: (language) => loadLanguageCatalog(language, assetBaseUrl),
      defaultLanguage: manifest.defaultLanguage,
      document,
      http,
      languages: manifest.languages
    });
    const context = createOldmanContext({
      assetBaseUrl,
      document,
      http,
      httpOptions: {},
      i18n
    });
    setOldmanContext(context);
    await context.i18n.init();
    const app = await startOldman({
      context,
      pageLoader: loadPageEntry
    });
    document.documentElement.dataset.omReady = "true";
    return app;
  })();

  try {
    return await appPromise;
  } catch (error) {
    appPromise = null;
    throw error;
  }
}

async function loadPageEntry(pageName: string): Promise<void> {
  const loader = pageEntries[`./pages/${pageName}.ts`];
  if (loader) await loader();
}

function readAssetBaseUrl(): string {
  const configured = document.querySelector<HTMLMetaElement>('meta[name="oldman-asset-base"]')?.content;
  if (configured) return new URL(configured, window.location.href).toString();
  return `${window.location.origin}/static/dist/`;
}

async function loadLanguageManifest(assetBaseUrl: string): Promise<LanguageManifest> {
  const response = await fetch(new URL("i18n/languages.json", assetBaseUrl));
  if (!response.ok) throw new Error("Unable to load the frontend language manifest");
  return response.json();
}

async function loadLanguageCatalog(
  language: LanguageDefinition,
  assetBaseUrl: string
): Promise<TranslationCatalog> {
  const url = new URL(language.catalogPath.replace(/^\/+/, ""), assetBaseUrl);
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) return { locale: language.locale, messages: {} };
  return response.json();
}

void startDashboard().catch((error: unknown) => {
  console.error("Oldman Dashboard startup failed", error);
});
