import axios, {
  AxiosHeaders,
  isAxiosError,
  isCancel,
  type AxiosAdapter,
  type AxiosInstance,
  type AxiosRequestConfig,
  type CreateAxiosDefaults,
  type RawAxiosHeaders
} from "axios";
import { getCsrfToken, isStateChangingMethod } from "./csrf";

export type HttpMethod = "get" | "post" | "put" | "patch" | "delete";
type RequestSignal = NonNullable<AxiosRequestConfig["signal"]>;

export interface HttpResult<T> {
  data: T;
  status: number;
}

export interface HttpRequestConfig extends AxiosRequestConfig {
  redirectOnAuth?: boolean;
}

export interface HttpClientOptions {
  baseURL?: string;
  timeout?: number;
  withCredentials?: boolean;
  adapter?: AxiosAdapter;
  authLoginPath?: string;
  onError?: HttpErrorHandler;
  onAuthRedirect?: (url: string) => void;
  signal?: AbortSignal;
}

export interface HttpErrorInfo {
  data?: unknown;
  error: unknown;
  isAxiosError: boolean;
  isCanceled: boolean;
  isNetworkError: boolean;
  method?: string;
  status?: number;
  url?: string;
}

export type HttpErrorHandler = (info: HttpErrorInfo) => void | Promise<void>;

export interface HttpClient {
  readonly axios: AxiosInstance;
  requestJson?<T>(method: HttpMethod, url: string, data?: unknown, config?: HttpRequestConfig): Promise<T>;
  getJson<T>(url: string, config?: HttpRequestConfig): Promise<T>;
  postJson<T>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T>;
  html(url: string, config?: HttpRequestConfig): Promise<string>;
  postForm<T>(url: string, form: HTMLFormElement, config?: HttpRequestConfig, submitter?: HTMLElement): Promise<HttpResult<T>>;
}

export function createHttpClient(options: HttpClientOptions = {}): HttpClient {
  const defaults: CreateAxiosDefaults = {
    baseURL: options.baseURL ?? "",
    timeout: options.timeout ?? 30000,
    withCredentials: options.withCredentials ?? true
  };

  if (options.adapter) {
    defaults.adapter = options.adapter;
  }

  const instance = axios.create(defaults);

  instance.interceptors.request.use((config) => {
    const headers = AxiosHeaders.from(config.headers);
    headers.set("X-Requested-With", "XMLHttpRequest");

    if (isStateChangingMethod(config.method ?? "get")) {
      const token = getCsrfToken();
      if (token) headers.set("X-CSRFToken", token);
    }

    config.headers = headers;
    const signal = combineAbortSignals(options.signal, config.signal);
    if (signal) config.signal = signal;
    return config;
  });

  instance.interceptors.response.use(
    (response) => response,
    async (error: unknown) => {
      if (isCancel(error)) return Promise.reject(error);
      const authRedirected = handleAuthRedirect(error, options.onAuthRedirect, options.authLoginPath ?? "/login");
      if (authRedirected) return Promise.reject(error);
      try {
        await options.onError?.(normalizeHttpError(error));
      } catch {
        // 错误钩子只处理弹窗、跳转等副作用，保留 Axios 原始 rejection。
      }

      return Promise.reject(error);
    }
  );

  return {
    axios: instance,
    async requestJson<T>(method: HttpMethod, url: string, data?: unknown, config?: AxiosRequestConfig) {
      const response = await instance.request<T>({
        ...config,
        headers: withAccept(config, "application/json"),
        method,
        url,
        data
      });
      return response.data;
    },
    async getJson<T>(url: string, config?: AxiosRequestConfig) {
      const response = await instance.get<T>(url, {
        ...config,
        headers: withAccept(config, "application/json")
      });
      return response.data;
    },
    async postJson<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
      const response = await instance.post<T>(url, data, {
        ...config,
        headers: withAccept(config, "application/json")
      });
      return response.data;
    },
    async html(url: string, config?: AxiosRequestConfig) {
      const response = await instance.get<string>(url, {
        ...config,
        headers: withAccept(config, "text/html"),
        responseType: "text"
      });
      return response.data;
    },
    async postForm<T>(url: string, form: HTMLFormElement, config?: AxiosRequestConfig, submitter?: HTMLElement) {
      const data = formData(form, submitter);
      const response = await instance.request<T>({
        ...config,
        method: config?.method ?? "post",
        url,
        data
      });
      return { data: response.data, status: response.status };
    }
  };
}

function withAccept(config: HttpRequestConfig | undefined, accept: string): AxiosHeaders {
  const headers = AxiosHeaders.from(config?.headers as AxiosHeaders | RawAxiosHeaders | string | undefined);
  headers.set("Accept", accept);
  return headers;
}

export function normalizeHttpError(error: unknown): HttpErrorInfo {
  const axiosError = isAxiosError(error);
  const canceled = isCancel(error);
  const response = axiosError ? error.response : undefined;
  const config = axiosError ? error.config : undefined;
  const status = response?.status;
  const data = response?.data;
  const method = config?.method;
  const url = config?.url;

  return {
    error,
    isAxiosError: axiosError,
    isCanceled: canceled,
    isNetworkError: axiosError && !response && !canceled,
    ...(data !== undefined ? { data } : {}),
    ...(method ? { method } : {}),
    ...(status !== undefined ? { status } : {}),
    ...(url ? { url } : {})
  };
}

function handleAuthRedirect(
  error: unknown,
  onAuthRedirect: ((url: string) => void) | undefined,
  authLoginPath: string
): boolean {
  if (!onAuthRedirect || !isAxiosError(error)) return false;
  if ((error.config as HttpRequestConfig | undefined)?.redirectOnAuth === false) {
    return false;
  }
  const response = error.response;
  if (!response || response.status !== 401) return false;
  const payload = authenticationPayload(response.data, response.headers);
  if (!isAuthenticationRequiredPayload(payload)) return false;
  const loginUrl = safeLoginUrl(payload.data?.login_url) ?? safeLoginUrl(authLoginPath);
  if (!loginUrl) return false;
  loginUrl.searchParams.set("next", `${window.location.pathname}${window.location.search}${window.location.hash}`);
  onAuthRedirect(`${loginUrl.pathname}${loginUrl.search}${loginUrl.hash}`);
  return true;
}

function authenticationPayload(data: unknown, headers: unknown): unknown {
  if (typeof data !== "string") return data;
  const contentType = String(AxiosHeaders.from(headers as RawAxiosHeaders).get("content-type") ?? "").toLowerCase();
  if (!contentType.includes("json")) return data;
  try {
    return JSON.parse(data) as unknown;
  } catch {
    return data;
  }
}

function isAuthenticationRequiredPayload(payload: unknown): payload is {
  error_code: 1401;
  data?: { login_url?: unknown };
} {
  return Boolean(payload && typeof payload === "object" && (payload as { error_code?: unknown }).error_code === 1401);
}

function safeLoginUrl(value: unknown): URL | null {
  if (typeof value !== "string" || !value || value.startsWith("//") || value.includes("\\")) return null;
  try {
    const url = new URL(value, window.location.href);
    return url.origin === window.location.origin && /^https?:$/.test(url.protocol) ? url : null;
  } catch {
    return null;
  }
}

function combineAbortSignals(
  defaultSignal: AbortSignal | undefined,
  requestSignal: RequestSignal | undefined
): RequestSignal | undefined {
  if (!defaultSignal) return requestSignal;
  if (!requestSignal) return defaultSignal;
  if (defaultSignal === requestSignal) return defaultSignal;

  if (typeof AbortSignal.any === "function" && isAbortSignal(requestSignal)) {
    return AbortSignal.any([defaultSignal, requestSignal]);
  }

  const controller = new AbortController();
  const abort = () => controller.abort();
  if (defaultSignal.aborted || requestSignal.aborted) {
    abort();
    return controller.signal;
  }

  defaultSignal.addEventListener("abort", abort, { once: true });
  addAbortListener(requestSignal, abort);
  return controller.signal;
}

function isAbortSignal(signal: RequestSignal): signal is AbortSignal {
  return typeof (signal as AbortSignal).addEventListener === "function";
}

function addAbortListener(signal: RequestSignal, listener: () => void): void {
  if (isAbortSignal(signal)) {
    signal.addEventListener("abort", listener, { once: true });
  }
}

function formData(form: HTMLFormElement, submitter?: HTMLElement): FormData {
  const fallbackBase = submitter ? new FormData(form) : undefined;
  const data = submitter ? new FormData(form, submitter) : new FormData(form);
  if (submitter && fallbackBase) appendSubmitterFallback(data, fallbackBase, submitter);
  return data;
}

function appendSubmitterFallback(data: FormData, fallbackBase: FormData, submitter: HTMLElement): void {
  if (!(submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement)) return;
  if (!submitter.name) return;

  const nativeCount = data.getAll(submitter.name).length;
  const baseCount = fallbackBase.getAll(submitter.name).length;
  if (nativeCount === baseCount) data.append(submitter.name, submitter.value);
}
