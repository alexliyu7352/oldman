import type { CleanupRegistry } from "./cleanup";

export type AssetDispose = "on-unmount" | "keep" | "manual";

export interface AssetOptions {
  attributes?: Record<string, string | number | boolean | null | undefined>;
  id?: string;
  once?: boolean;
  dispose?: AssetDispose;
  nonce?: string;
  onRemove?: (element: AssetElement) => void;
}

export interface StylesheetAssetOptions extends AssetOptions {
  media?: string;
  integrity?: string;
  crossOrigin?: string;
  referrerPolicy?: ReferrerPolicy;
}

export interface ScriptAssetOptions extends AssetOptions {
  type?: "text/javascript" | "module" | string;
  async?: boolean;
  defer?: boolean;
  integrity?: string;
  crossOrigin?: string;
  referrerPolicy?: ReferrerPolicy;
  removeOnError?: boolean;
}

export type StylesheetAssetInput = string | ({ href: string } & StylesheetAssetOptions);
export type ScriptAssetInput = string | ({ src: string } & ScriptAssetOptions);
export type AssetElement = HTMLLinkElement | HTMLScriptElement;

export interface AssetBundleOptions {
  stylesheets?: StylesheetAssetInput[];
  scripts?: ScriptAssetInput[];
  stylesheetDefaults?: StylesheetAssetOptions;
  scriptDefaults?: ScriptAssetOptions;
  parallelScripts?: boolean;
}

export interface AssetBundleResult {
  stylesheets: HTMLLinkElement[];
  scripts: HTMLScriptElement[];
}

interface ScriptLoadRecord {
  promise: Promise<HTMLScriptElement>;
  reject: (reason?: unknown) => void;
}

const scriptLoadRecords = new WeakMap<HTMLScriptElement, ScriptLoadRecord>();
const loadedScripts = new WeakSet<HTMLScriptElement>();
const failedScripts = new WeakSet<HTMLScriptElement>();
const assetRemoveCallbacks = new WeakMap<AssetElement, (element: AssetElement) => void>();

export class AssetService {
  constructor(private readonly cleanup: CleanupRegistry) {}

  async loadBundle(options: AssetBundleOptions): Promise<AssetBundleResult> {
    const stylesheets = (options.stylesheets ?? []).map((asset) => {
      const { href, assetOptions } = normalizeStylesheetAsset(asset, options.stylesheetDefaults);
      return this.stylesheet(href, assetOptions);
    });

    const scriptInputs = options.scripts ?? [];
    const scripts = options.parallelScripts
      ? await Promise.all(
          scriptInputs.map((asset) => {
            const { src, assetOptions } = normalizeScriptAsset(asset, options.scriptDefaults);
            return this.script(src, assetOptions);
          })
        )
      : await this.loadScriptsInOrder(scriptInputs, options.scriptDefaults);

    return { stylesheets, scripts };
  }

  remove(asset: string | AssetElement): boolean {
    const element = typeof asset === "string" ? document.getElementById(asset) : asset;
    if (element instanceof HTMLScriptElement) {
      this.removeScript(element, `Script load manually removed before completion: ${scriptSource(element)}`);
      return true;
    }

    if (element instanceof HTMLLinkElement) {
      removeAssetElement(element);
      return true;
    }

    return false;
  }

  removeBundle(bundle: AssetBundleResult): void {
    for (const script of bundle.scripts) {
      this.remove(script);
    }

    for (const stylesheet of bundle.stylesheets) {
      this.remove(stylesheet);
    }
  }

  stylesheet(href: string, options: StylesheetAssetOptions = {}): HTMLLinkElement {
    const existing = options.id ? document.getElementById(options.id) : null;
    if (existing instanceof HTMLLinkElement && options.once !== false) return existing;
    if (existing instanceof HTMLLinkElement) removeAssetElement(existing);

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    if (options.id) link.id = options.id;
    if (options.media) link.media = options.media;
    if (options.integrity) link.integrity = options.integrity;
    if (options.crossOrigin) link.crossOrigin = options.crossOrigin;
    if (options.referrerPolicy) link.referrerPolicy = options.referrerPolicy;
    if (options.nonce) link.nonce = options.nonce;
    applyAttributes(link, options.attributes, protectedLinkAttributes);
    registerAssetRemoveCallback(link, options.onRemove);
    document.head.appendChild(link);

    if ((options.dispose ?? "on-unmount") === "on-unmount") {
      this.cleanup.add(() => removeAssetElement(link));
    }

    return link;
  }

  script(src: string, options: ScriptAssetOptions = {}): Promise<HTMLScriptElement> {
    const existing = options.id ? document.getElementById(options.id) : null;
    if (existing instanceof HTMLScriptElement) {
      if (options.once !== false) {
        const pending = scriptLoadRecords.get(existing);
        if (pending) return pending.promise;
        if (loadedScripts.has(existing)) return Promise.resolve(existing);
        if (failedScripts.has(existing)) {
          removeAssetElement(existing);
        } else {
          return Promise.resolve(existing);
        }
      } else {
        this.removeScript(existing, `Script load replaced before completion: ${src}`);
      }
    }

    const script = document.createElement("script");
    script.type = options.type ?? "text/javascript";
    script.src = src;
    if (options.id) script.id = options.id;
    if (options.async !== undefined) script.async = options.async;
    if (options.defer !== undefined) script.defer = options.defer;
    if (options.integrity) script.integrity = options.integrity;
    if (options.crossOrigin) script.crossOrigin = options.crossOrigin;
    if (options.referrerPolicy) script.referrerPolicy = options.referrerPolicy;
    if (options.nonce) script.nonce = options.nonce;
    applyAttributes(script, options.attributes, protectedScriptAttributes);
    registerAssetRemoveCallback(script, options.onRemove);

    let rejectLoad: (reason?: unknown) => void = () => {};
    const promise = new Promise<HTMLScriptElement>((resolve, reject) => {
      rejectLoad = reject;
      script.addEventListener(
        "load",
        () => {
          scriptLoadRecords.delete(script);
          loadedScripts.add(script);
          resolve(script);
        },
        { once: true }
      );
      script.addEventListener(
        "error",
        () => {
          scriptLoadRecords.delete(script);
          failedScripts.add(script);
          reject(new Error(`Failed to load script: ${src}`));
          if (options.removeOnError !== false) {
            removeAssetElement(script);
          }
        },
        { once: true }
      );
    });
    scriptLoadRecords.set(script, { promise, reject: rejectLoad });

    document.body.appendChild(script);

    if ((options.dispose ?? "keep") === "on-unmount") {
      this.cleanup.add(() => this.removeScript(script, `Script load removed before completion: ${src}`));
    }

    return promise;
  }

  private async loadScriptsInOrder(
    scripts: ScriptAssetInput[],
    defaults: ScriptAssetOptions | undefined
  ): Promise<HTMLScriptElement[]> {
    const loaded: HTMLScriptElement[] = [];
    for (const asset of scripts) {
      const { src, assetOptions } = normalizeScriptAsset(asset, defaults);
      loaded.push(await this.script(src, assetOptions));
    }
    return loaded;
  }

  private removeScript(script: HTMLScriptElement, pendingMessage: string): void {
    const pending = scriptLoadRecords.get(script);
    if (pending) {
      scriptLoadRecords.delete(script);
      pending.reject(new Error(pendingMessage));
    }
    removeAssetElement(script);
  }
}

const protectedLinkAttributes = new Set(["href", "rel"]);
const protectedScriptAttributes = new Set(["src", "type"]);

function normalizeStylesheetAsset(
  asset: StylesheetAssetInput,
  defaults: StylesheetAssetOptions | undefined
): { href: string; assetOptions: StylesheetAssetOptions } {
  if (typeof asset === "string") return { href: asset, assetOptions: mergeAssetOptions(defaults, {}) };

  const { href, ...assetOptions } = asset;
  return { href, assetOptions: mergeAssetOptions(defaults, assetOptions) };
}

function normalizeScriptAsset(
  asset: ScriptAssetInput,
  defaults: ScriptAssetOptions | undefined
): { src: string; assetOptions: ScriptAssetOptions } {
  if (typeof asset === "string") return { src: asset, assetOptions: mergeAssetOptions(defaults, {}) };

  const { src, ...assetOptions } = asset;
  return { src, assetOptions: mergeAssetOptions(defaults, assetOptions) };
}

function scriptSource(script: HTMLScriptElement): string {
  return script.getAttribute("src") ?? script.src;
}

function registerAssetRemoveCallback(
  element: AssetElement,
  callback: ((element: AssetElement) => void) | undefined
): void {
  if (callback) assetRemoveCallbacks.set(element, callback);
}

function removeAssetElement(element: AssetElement): void {
  const callback = assetRemoveCallbacks.get(element);
  assetRemoveCallbacks.delete(element);
  try {
    if (callback) callback(element);
  } finally {
    element.remove();
  }
}

function mergeAssetOptions<TOptions extends AssetOptions>(
  defaults: TOptions | undefined,
  options: TOptions
): TOptions {
  return {
    ...defaults,
    ...options,
    attributes: {
      ...defaults?.attributes,
      ...options.attributes
    }
  };
}

function applyAttributes(
  element: HTMLElement,
  attributes: Record<string, string | number | boolean | null | undefined> | undefined,
  protectedAttributes: Set<string>
): void {
  if (!attributes) return;

  for (const [name, value] of Object.entries(attributes)) {
    const normalizedName = name.toLowerCase();
    if (protectedAttributes.has(normalizedName)) continue;
    if (value === null || value === undefined || value === false) continue;
    if (value === true) {
      element.setAttribute(name, "");
      continue;
    }
    element.setAttribute(name, String(value));
  }
}
