import { deleteCookie, getCookie, setCookie, type CookieOptions } from "../http/cookies";

export type PreferenceStoreBackend = "local" | "session" | "cookie" | "memory" | Storage;

export interface PreferenceStoreOptions {
  backend?: PreferenceStoreBackend;
  cookie?: CookieOptions;
  namespace?: string;
}

export class PreferenceStore {
  private readonly backend: PreferenceStoreBackend;
  private readonly cookieOptions: CookieOptions;
  private readonly fallback = new Map<string, string>();
  private readonly prefix: string;

  constructor(options: PreferenceStoreOptions = {}) {
    this.backend = options.backend ?? "local";
    this.cookieOptions = options.cookie ?? {};
    const namespace = options.namespace ?? "oldman";
    this.prefix = namespace ? `${namespace}:` : "";
  }

  get(key: string): string | null {
    const storageKey = this.storageKey(key);
    if (this.backend === "cookie") return getCookie(storageKey);
    if (this.backend === "memory") return this.fallback.get(storageKey) ?? null;

    const storage = this.resolveStorage();
    if (!storage) return this.fallback.get(storageKey) ?? null;

    try {
      return storage.getItem(storageKey);
    } catch {
      return this.fallback.get(storageKey) ?? null;
    }
  }

  set(key: string, value: string): void {
    const storageKey = this.storageKey(key);
    if (this.backend === "cookie") {
      setCookie(storageKey, value, this.cookieOptions);
      return;
    }

    if (this.backend === "memory") {
      this.fallback.set(storageKey, value);
      return;
    }

    const storage = this.resolveStorage();
    if (!storage) {
      this.fallback.set(storageKey, value);
      return;
    }

    try {
      storage.setItem(storageKey, value);
      this.fallback.delete(storageKey);
    } catch {
      this.fallback.set(storageKey, value);
    }
  }

  remove(key: string): void {
    const storageKey = this.storageKey(key);
    this.fallback.delete(storageKey);

    if (this.backend === "cookie") {
      const options: Pick<CookieOptions, "domain" | "path"> = {};
      if (this.cookieOptions.domain) options.domain = this.cookieOptions.domain;
      if (this.cookieOptions.path) options.path = this.cookieOptions.path;
      deleteCookie(storageKey, options);
      return;
    }

    if (this.backend === "memory") return;

    const storage = this.resolveStorage();
    if (!storage) return;

    try {
      storage.removeItem(storageKey);
    } catch {
      // 忽略存储清理失败，调用方不需要处理浏览器配额或安全状态差异。
    }
  }

  getJson<T>(key: string): T | null;
  getJson<T>(key: string, fallback: T): T;
  getJson<T>(key: string, fallback?: T): T | null {
    const value = this.get(key);
    if (value === null) return fallback ?? null;

    try {
      return JSON.parse(value) as T;
    } catch {
      return fallback ?? null;
    }
  }

  setJson(key: string, value: unknown): void {
    this.set(key, JSON.stringify(value));
  }

  updateJson<T>(key: string, updater: (current: T | null) => T | null | undefined): T | null {
    const next = updater(this.getJson<T>(key));
    if (next === null || next === undefined) {
      this.remove(key);
      return null;
    }

    this.setJson(key, next);
    return next;
  }

  private storageKey(key: string): string {
    return `${this.prefix}${key}`;
  }

  private resolveStorage(): Storage | null {
    if (isStorage(this.backend)) return this.backend;
    if (typeof window === "undefined") return null;

    try {
      if (this.backend === "session") return window.sessionStorage;
      return window.localStorage;
    } catch {
      return null;
    }
  }
}

export function createPreferenceStore(options: PreferenceStoreOptions = {}): PreferenceStore {
  return new PreferenceStore(options);
}

function isStorage(value: PreferenceStoreBackend): value is Storage {
  return typeof value === "object" && value !== null && "getItem" in value && "setItem" in value && "removeItem" in value;
}
