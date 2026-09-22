import "./app.css";
import {
  createFetchCatalogLoader,
  createHttpClient,
  createI18n,
  createOldmanContext,
  readAssetBaseUrl,
  setOldmanContext,
  startOldman,
  type OldmanApp
} from "oldman-web/core";
import { defaultLanguage, languageAliases, languageDefinitions } from "./i18n/generated";

const pageEntries = import.meta.glob("./pages/*.ts");
let appPromise: Promise<OldmanApp> | null = null;

export async function startDashboard(): Promise<OldmanApp> {
  if (appPromise) return appPromise;

  appPromise = (async () => {
    const http = createHttpClient({});
    const assetBaseUrl = readAssetBaseUrl();
    const i18n = createI18n({
      aliases: languageAliases,
      catalogLoader: createFetchCatalogLoader({ assetBaseUrl }),
      defaultLanguage,
      document,
      http,
      languages: languageDefinitions
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

void startDashboard().catch((error: unknown) => {
  console.error("Oldman Dashboard startup failed", error);
});
