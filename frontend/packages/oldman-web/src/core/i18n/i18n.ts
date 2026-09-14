import type { HttpClient } from "../http/client";
import { getCookie, setCookie } from "../http/cookies";
import { selectPluralIndex } from "./plural";

export type TranslationValue = string | string[];
export type TranslationMessages = Record<string, TranslationValue>;
export type TranslationParams = Record<string, string | number | boolean | null | undefined>;

export interface TranslationCatalog {
  locale: string;
  messages: TranslationMessages;
  pluralRule?: string;
}

export interface LanguageDefinition {
  readonly code: string;
  readonly locale: string;
  readonly aliases: readonly string[];
  readonly flag: string;
  readonly flagUrl?: string;
  readonly catalogPath: string;
  readonly name: string;
}

export interface LanguageChangeDetail {
  language: string;
  locale: string;
  runtime: I18nRuntime;
}

export interface SetLanguageOptions {
  persist?: boolean;
  syncBackend?: boolean;
  translateDocument?: boolean;
}

export interface CreateI18nOptions {
  defaultLanguage?: string;
  languages?: readonly LanguageDefinition[];
  aliases?: Record<string, string>;
  document?: Document;
  catalogLoader?: I18nCatalogLoader;
  http?: Pick<HttpClient, "postJson">;
  initialCatalog?: TranslationCatalog;
  languagePreferencePath?: string | null;
}

export interface I18nRuntime {
  readonly locale: string;
  readonly currentLanguage: string;
  readonly languages: readonly LanguageDefinition[];
  init(): Promise<I18nRuntime>;
  setLanguage(language: string, options?: SetLanguageOptions): Promise<string>;
  resolveLanguageCode(language: string | null | undefined): string;
  getLanguageDefinition(language: string): LanguageDefinition;
  translateDocument(root?: ParentNode): void;
  setCatalog(catalog: TranslationCatalog): void;
  t(message: string, params?: TranslationParams): string;
  tc(context: string, message: string, params?: TranslationParams): string;
  tn(singular: string, plural: string, count: number, params?: TranslationParams): string;
  tnc(context: string, singular: string, plural: string, count: number, params?: TranslationParams): string;
}

export type TranslationCatalogLoader = (locale: string) => Promise<TranslationCatalog | null | undefined>;
export type I18nCatalogLoader = (language: LanguageDefinition) => Promise<TranslationCatalog | null | undefined>;

const CONTEXT_SEPARATOR = "\u0004";
const LANGUAGE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60;

export function createI18n(catalog: TranslationCatalog): I18nRuntime;
export function createI18n(options: CreateI18nOptions): I18nRuntime;
export function createI18n(input: TranslationCatalog | CreateI18nOptions): I18nRuntime {
  const options = normalizeCreateOptions(input);
  const runtimeDocument = options.document ?? document;
  const languages = normalizeLanguages(options);
  const languageByCode = new Map(languages.map((language) => [language.code, language]));
  const aliases = buildLanguageAliases(languages, options.aliases ?? {});
  const defaultLanguage = resolveConfiguredDefault(options.defaultLanguage, languages, aliases);
  const catalogLoader = options.catalogLoader;
  const catalogCache = new Map<string, TranslationCatalog>();
  let currentCatalog = options.initialCatalog ?? {
    locale: getLanguageDefinition(defaultLanguage).locale,
    messages: {}
  };
  let currentLanguage = resolveLanguageCode(currentCatalog.locale);
  let initPromise: Promise<I18nRuntime> | null = null;
  let languageChangeSequence = 0;

  const runtime: I18nRuntime = {
    get locale() {
      return currentCatalog.locale;
    },
    get currentLanguage() {
      return currentLanguage;
    },
    get languages() {
      return languages;
    },
    async init() {
      initPromise ??= (async () => {
        await applyLanguage(detectInitialLanguage(), {
          persist: false,
          syncBackend: false,
          translateDocument: true
        });
        return runtime;
      })();
      return initPromise;
    },
    async setLanguage(language, setOptions = {}) {
      return applyLanguage(language, {
        persist: setOptions.persist ?? true,
        syncBackend: setOptions.syncBackend ?? true,
        translateDocument: setOptions.translateDocument ?? true
      });
    },
    resolveLanguageCode,
    getLanguageDefinition(language) {
      return getLanguageDefinition(resolveLanguageCode(language));
    },
    translateDocument(root = runtimeDocument) {
      for (const element of root.querySelectorAll<HTMLElement>("[data-key]")) {
        const key = element.dataset.key;
        if (key) element.textContent = runtime.t(key);
      }
    },
    setCatalog(nextCatalog) {
      currentCatalog = nextCatalog;
      currentLanguage = resolveLanguageCode(nextCatalog.locale);
    },
    t(message, params = {}) {
      const translated = currentCatalog.messages[message];
      const value = Array.isArray(translated) ? translated[0] ?? message : translated ?? message;
      return interpolate(value, params);
    },
    tc(context, message, params = {}) {
      const translated = currentCatalog.messages[contextKey(context, message)];
      const value = Array.isArray(translated) ? translated[0] ?? message : translated ?? message;
      return interpolate(value, params);
    },
    tn(singular, plural, count, params = {}) {
      return translatePlural(currentCatalog, singular, singular, plural, count, params);
    },
    tnc(context, singular, plural, count, params = {}) {
      return translatePlural(currentCatalog, contextKey(context, singular), singular, plural, count, params);
    }
  };

  return runtime;

  async function applyLanguage(language: string, setOptions: Required<SetLanguageOptions>): Promise<string> {
    const sequence = ++languageChangeSequence;
    const languageCode = resolveLanguageCode(language);
    const definition = getLanguageDefinition(languageCode);
    const catalog = await loadCatalog(definition);
    if (sequence !== languageChangeSequence) return currentLanguage;

    currentCatalog = catalog;
    currentLanguage = languageCode;
    runtimeDocument.documentElement.lang = languageCode;

    if (setOptions.translateDocument) runtime.translateDocument();
    if (setOptions.persist) persistLanguagePreference(languageCode);
    if (setOptions.syncBackend) await syncBackendLanguage(languageCode);
    if (sequence !== languageChangeSequence) return currentLanguage;

    runtimeDocument.dispatchEvent(
      new CustomEvent<LanguageChangeDetail>("om:i18n:change", {
        detail: {
          language: languageCode,
          locale: definition.locale,
          runtime
        }
      })
    );

    return languageCode;
  }

  async function loadCatalog(language: LanguageDefinition): Promise<TranslationCatalog> {
    const cached = catalogCache.get(language.code);
    if (cached) return cached;

    const loaded = (await catalogLoader?.(language)) ?? {
      locale: language.locale,
      messages: {}
    };
    const catalog = {
      locale: loaded.locale || language.locale,
      messages: loaded.messages ?? {},
      ...(loaded.pluralRule ? { pluralRule: loaded.pluralRule } : {})
    };
    catalogCache.set(language.code, catalog);
    return catalog;
  }

  function detectInitialLanguage(): string {
    const candidates = [
      safeLocalStorageGet("preferred_language"),
      getCookie("preferred_language"),
      getCookie("lang"),
      runtimeDocument.documentElement.lang,
      ...browserLanguages(),
      defaultLanguage
    ];
    for (const candidate of candidates) {
      const resolved = tryResolveLanguageCode(candidate);
      if (resolved) return resolved;
    }
    return defaultLanguage;
  }

  function resolveLanguageCode(language: string | null | undefined): string {
    return tryResolveLanguageCode(language) ?? defaultLanguage;
  }

  function tryResolveLanguageCode(language: string | null | undefined): string | null {
    for (const candidate of languageCodeCandidates(language || "")) {
      const aliased = aliases[candidate] ?? candidate;
      if (languageByCode.has(aliased)) return aliased;
    }
    return null;
  }

  function getLanguageDefinition(language: string): LanguageDefinition {
    return languageByCode.get(language) ?? languageByCode.get(defaultLanguage) ?? languages[0] ?? defaultLanguageDefinition();
  }

  function browserLanguages(): string[] {
    const navigatorLanguages = runtimeDocument.defaultView?.navigator.languages ?? [];
    const navigatorLanguage = runtimeDocument.defaultView?.navigator.language;
    return [...navigatorLanguages, navigatorLanguage].filter((value): value is string => Boolean(value));
  }

  function persistLanguagePreference(language: string): void {
    safeLocalStorageSet("preferred_language", language);
    setCookie("preferred_language", language, { path: "/", maxAge: LANGUAGE_COOKIE_MAX_AGE, sameSite: "Lax" });
    setCookie("lang", language, { path: "/", maxAge: LANGUAGE_COOKIE_MAX_AGE, sameSite: "Lax" });
  }

  async function syncBackendLanguage(language: string): Promise<void> {
    if (!options.http || options.languagePreferencePath === null) return;

    try {
      await options.http.postJson(options.languagePreferencePath || "/preferences/language", { language });
    } catch (error) {
      if (!isCanceledRequest(error)) console.warn("Failed to save language preference", error);
    }
  }

  function safeLocalStorageGet(key: string): string | null {
    try {
      return runtimeDocument.defaultView?.localStorage.getItem(key) ?? null;
    } catch {
      return null;
    }
  }

  function safeLocalStorageSet(key: string, value: string): void {
    try {
      runtimeDocument.defaultView?.localStorage.setItem(key, value);
    } catch {
      // 浏览器禁用存储时，当前页面仍应完成语言切换。
    }
  }
}

export function contextKey(context: string, message: string): string {
  return `${context}${CONTEXT_SEPARATOR}${message}`;
}

export function interpolate(message: string, params: TranslationParams = {}): string {
  return message.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key: string) => {
    const value = params[key];
    return value === undefined || value === null ? match : String(value);
  });
}

export function localeCandidates(locale: string): string[] {
  const normalized = locale.trim();
  if (!normalized) return [];

  const candidates = new Set<string>();
  candidates.add(normalized);
  candidates.add(normalized.replaceAll("-", "_"));
  candidates.add(normalized.replaceAll("_", "-"));

  const separator = normalized.includes("-") ? "-" : "_";
  const baseLocale = normalized.split(separator)[0];
  if (baseLocale) candidates.add(baseLocale);

  return [...candidates];
}

export async function loadCatalogForLocale(
  locale: string,
  loader: TranslationCatalogLoader
): Promise<TranslationCatalog | null> {
  for (const candidate of localeCandidates(locale)) {
    const catalog = await loader(candidate);
    if (catalog) return catalog;
  }

  return null;
}

export async function loadI18nCatalog(
  runtime: I18nRuntime,
  locale: string,
  loader: TranslationCatalogLoader
): Promise<TranslationCatalog | null> {
  const catalog = await loadCatalogForLocale(locale, loader);
  if (catalog) runtime.setCatalog(catalog);
  return catalog;
}

function normalizeCreateOptions(input: TranslationCatalog | CreateI18nOptions): Required<Pick<CreateI18nOptions, "aliases">> &
  Omit<CreateI18nOptions, "aliases"> {
  if ("messages" in input) {
    return {
      defaultLanguage: input.locale,
      languages: [
        {
          code: input.locale,
          locale: input.locale,
          aliases: [],
          flag: "",
          catalogPath: "",
          name: input.locale
        }
      ],
      aliases: {},
      initialCatalog: input
    };
  }

  return {
    aliases: {},
    ...input
  };
}

function normalizeLanguages(options: CreateI18nOptions): readonly LanguageDefinition[] {
  if (options.languages?.length) return options.languages;

  const catalog = options.initialCatalog;
  const code = options.defaultLanguage || catalog?.locale || "en";
  return [
    {
      code,
      locale: catalog?.locale || code,
      aliases: [],
      flag: "",
      catalogPath: "",
      name: code
    }
  ];
}

function defaultLanguageDefinition(): LanguageDefinition {
  return {
    code: "en",
    locale: "en",
    aliases: [],
    flag: "",
    catalogPath: "",
    name: "en"
  };
}

function resolveConfiguredDefault(
  configuredDefault: string | undefined,
  languages: readonly LanguageDefinition[],
  aliases: Record<string, string>
): string {
  for (const candidate of languageCodeCandidates(configuredDefault || "")) {
    const aliased = aliases[candidate] ?? candidate;
    if (languages.some((language) => language.code === aliased)) return aliased;
  }
  return languages[0]?.code ?? "en";
}

function buildLanguageAliases(
  languages: readonly LanguageDefinition[],
  configuredAliases: Record<string, string>
): Record<string, string> {
  const aliases: Record<string, string> = {};
  for (const language of languages) {
    const candidates = [language.code, language.locale, ...language.aliases];
    for (const candidate of candidates) {
      for (const variant of languageCodeCandidates(candidate)) {
        aliases[variant] = language.code;
      }
    }
  }
  for (const [alias, code] of Object.entries(configuredAliases)) {
    aliases[alias] = code;
  }
  return aliases;
}

function languageCodeCandidates(language: string): string[] {
  const raw = language.trim();
  if (!raw) return [];

  const variants = [
    raw,
    raw.toLowerCase(),
    raw.replaceAll("_", "-").toLowerCase(),
    raw.replaceAll("-", "_").toLowerCase()
  ];
  const seen = new Set<string>();
  return variants.filter((variant) => {
    if (!variant || seen.has(variant)) return false;
    seen.add(variant);
    return true;
  });
}

function translatePlural(
  catalog: TranslationCatalog,
  key: string,
  singular: string,
  plural: string,
  count: number,
  params: TranslationParams
): string {
  const translated = catalog.messages[key];
  const forms = Array.isArray(translated) ? translated : [translated ?? singular, plural];
  const index = selectPluralIndex(catalog.pluralRule, count);
  const candidate = forms[index];
  const fallback = index === 0 ? singular : plural;
  const value = typeof candidate === "string" && candidate !== "" ? candidate : fallback;
  return interpolate(value, {
    count,
    ...params
  });
}

function isCanceledRequest(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { __CANCEL__?: unknown; code?: unknown };
  return candidate.__CANCEL__ === true || candidate.code === "ERR_CANCELED";
}

export { selectPluralIndex };
