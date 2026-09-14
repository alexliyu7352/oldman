import { ComponentRegistry, globalComponentRegistry } from "../component/registry";
import { createHttpClient, type HttpClient, type HttpClientOptions } from "../http/client";
import { createI18n, type I18nRuntime } from "../i18n";
import { PageRegistry } from "../page/registry";
import { consoleLogger, type Logger } from "../services/logger";

export interface OldmanContext {
  readonly document: Document;
  readonly assetBaseUrl: string;
  readonly i18n: I18nRuntime;
  readonly http: HttpClient;
  readonly logger: Logger;
  readonly pageRegistry: PageRegistry;
  readonly componentRegistry: ComponentRegistry;
  createHttpClient(options?: HttpClientOptions): HttpClient;
  assetUrl(path: string): string;
}

export interface CreateOldmanContextOptions {
  document?: Document;
  assetBaseUrl?: string;
  i18n?: I18nRuntime;
  http?: HttpClient;
  httpFactory?: (options?: HttpClientOptions) => HttpClient;
  httpOptions?: HttpClientOptions;
  logger?: Logger;
  pageRegistry?: PageRegistry;
  componentRegistry?: ComponentRegistry;
}

let currentContext: OldmanContext | null = null;

export function createOldmanContext(options: CreateOldmanContextOptions = {}): OldmanContext {
  const contextDocument = options.document ?? document;
  const assetBaseUrl = normalizeAssetBaseUrl(options.assetBaseUrl ?? readAssetBaseUrl(contextDocument));
  const httpFactory = options.httpFactory ?? createHttpClient;
  const httpOptions = withDefaultAuthRedirect(options.httpOptions);
  const sharedHttp = options.http ?? httpFactory(httpOptions);
  const canCreateScopedHttp = Boolean(options.httpFactory || options.httpOptions);

  return {
    document: contextDocument,
    assetBaseUrl,
    i18n: options.i18n ?? createI18n({ locale: contextDocument.documentElement.lang || "en", messages: {} }),
    http: sharedHttp,
    logger: options.logger ?? consoleLogger,
    pageRegistry: options.pageRegistry ?? new PageRegistry(),
    componentRegistry: options.componentRegistry ?? new ComponentRegistry(globalComponentRegistry),
    createHttpClient(scopedOptions: HttpClientOptions = {}) {
      if (options.http && !canCreateScopedHttp) return options.http;
      return httpFactory(withDefaultAuthRedirect({ ...httpOptions, ...scopedOptions }));
    },
    assetUrl(path: string) {
      return new URL(path.replace(/^\/+/, ""), assetBaseUrl).toString();
    }
  };
}

function withDefaultAuthRedirect(options: HttpClientOptions | undefined): HttpClientOptions {
  return {
    ...options,
    onAuthRedirect: options?.onAuthRedirect ?? redirectToLogin
  };
}

function redirectToLogin(url: string): void {
  window.location.assign(url);
}

export function getOldmanContext(): OldmanContext {
  currentContext ??= createOldmanContext();
  return currentContext;
}

export function setOldmanContext(context: OldmanContext): void {
  currentContext = context;
}

export function resetOldmanContext(): void {
  currentContext = null;
}

function readAssetBaseUrl(contextDocument: Document): string {
  return (
    contextDocument.documentElement.dataset.omAssetBaseUrl ||
    contextDocument.body?.dataset.omAssetBaseUrl ||
    contextDocument.baseURI ||
    window.location.href
  );
}

function normalizeAssetBaseUrl(value: string): string {
  return value.endsWith("/") ? value : `${value}/`;
}
