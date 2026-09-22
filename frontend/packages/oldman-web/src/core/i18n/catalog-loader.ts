import type { I18nCatalogLoader, LanguageDefinition, TranslationCatalog } from "./i18n";

/**
 * 读取页面声明的静态资源根地址。
 *
 * 服务端在 `<meta name="oldman-asset-base">` 写入当前 bundle 的地址（开发模式是 Vite 服务，
 * 生产模式是收集后的 manifest 目录）。没有这个 meta 时回落到 `fallback`，默认是站点根。
 */
export function readAssetBaseUrl(options: ReadAssetBaseUrlOptions = {}): string {
  const scope = options.document ?? document;
  const configured = scope.querySelector<HTMLMetaElement>('meta[name="oldman-asset-base"]')?.content;
  const base = options.baseHref ?? scope.defaultView?.location.href ?? window.location.href;
  if (configured) return new URL(configured, base).toString();

  return options.fallback ?? new URL("/", base).toString();
}

export interface ReadAssetBaseUrlOptions {
  /** 查找 meta 的文档，默认当前文档。 */
  document?: Document;
  /** 解析相对地址的基准，默认当前地址。 */
  baseHref?: string;
  /** 没有 meta 时使用的地址，默认站点根。 */
  fallback?: string;
}

/**
 * 按语言定义 fetch 一份 JSON 目录的 catalog loader。
 *
 * `catalogPath` 按 URL 规则原样解析，不做改写：项目的语言包和 bundle 放在一起，写相对路径
 * （`i18n/en.json`），相对 `assetBaseUrl` 解析；框架 Admin 的语言包是挂在它自己前缀下的一条路由
 * （`/admin/i18n/en.json`），和 bundle 不在同一个挂载点，写站点绝对路径。剥掉前导斜杠会把后者
 * 变成相对当前页面，于是每个非根页面都请求到一个 404 上。
 *
 * 取不到、HTTP 失败或者内容不是目录时返回空目录：缺翻译要退回 msgid，不能让整页启动失败。
 * `initialCatalog` 是服务端已经内联的当前语言目录，命中时直接用，不再发一次请求。
 */
export function createFetchCatalogLoader(options: CreateFetchCatalogLoaderOptions = {}): I18nCatalogLoader {
  const { assetBaseUrl, initialCatalog, initialLanguage, fetchImpl } = options;

  return async (language: LanguageDefinition): Promise<TranslationCatalog> => {
    const empty: TranslationCatalog = { locale: language.locale, messages: {} };
    if (initialCatalog && initialLanguage && language.code === initialLanguage) return initialCatalog;
    if (!language.catalogPath) return empty;

    const base = assetBaseUrl ?? window.location.href;
    const url = new URL(language.catalogPath, base).toString();
    try {
      const request = fetchImpl ?? fetch;
      const response = await request(url, { headers: { Accept: "application/json" } });
      if (!response.ok) return empty;
      const catalog = await response.json() as unknown;
      return isTranslationCatalog(catalog) ? catalog : empty;
    } catch {
      return empty;
    }
  };
}

export interface CreateFetchCatalogLoaderOptions {
  /** 目录地址的基准，通常是 `readAssetBaseUrl()` 的结果。 */
  assetBaseUrl?: string;
  /** 服务端内联的目录。 */
  initialCatalog?: TranslationCatalog;
  /** `initialCatalog` 对应的语言 code。 */
  initialLanguage?: string;
  /** 注入的 fetch，供测试使用。 */
  fetchImpl?: typeof fetch;
}

function isTranslationCatalog(value: unknown): value is TranslationCatalog {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { locale?: unknown; messages?: unknown };
  return typeof candidate.locale === "string" && typeof candidate.messages === "object" && candidate.messages !== null;
}
