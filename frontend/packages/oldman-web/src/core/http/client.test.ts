import {
  type AxiosAdapter,
  AxiosError,
  CanceledError,
  type AxiosResponse,
  AxiosHeaders,
  type InternalAxiosRequestConfig
} from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpClient, normalizeHttpError } from "./client";

function response(config: InternalAxiosRequestConfig, data: unknown): AxiosResponse {
  return {
    data,
    status: 200,
    statusText: "OK",
    headers: {},
    config,
    request: {}
  };
}

describe("createHttpClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.replaceChildren();
    document.head.replaceChildren();
    window.history.replaceState({}, "", "/");
    for (const cookie of document.cookie.split(";")) {
      const name = cookie.split("=")[0]?.trim();
      if (name) document.cookie = `${name}=; Max-Age=0; Path=/`;
    }
  });

  it("adds csrf header for post requests", async () => {
    document.head.innerHTML = `<meta name="csrf-token" content="token-1">`;
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    await http.postJson("/save", { name: "Oldman" });

    const headers = AxiosHeaders.from(adapter.mock.calls[0]![0].headers);
    expect(headers.get("X-CSRFToken")).toBe("token-1");
    expect(headers.get("X-Requested-With")).toBe("XMLHttpRequest");
  });

  it("prefers hidden csrf field for state changing requests", async () => {
    document.body.innerHTML = `<input type="hidden" name="csrfmiddlewaretoken" value="hidden-token">`;
    document.head.innerHTML = `<meta name="csrf-token" content="meta-token">`;
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    await http.postJson("/save", { name: "Oldman" });

    const headers = AxiosHeaders.from(adapter.mock.calls[0]![0].headers);
    expect(headers.get("X-CSRFToken")).toBe("hidden-token");
  });

  it("falls back to csrftoken cookie for state changing requests", async () => {
    document.cookie = "csrftoken=cookie-token; Path=/";
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    await http.postJson("/save", { name: "Oldman" });

    const headers = AxiosHeaders.from(adapter.mock.calls[0]![0].headers);
    expect(headers.get("X-CSRFToken")).toBe("cookie-token");
  });

  it("returns html response text", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, "<div>ok</div>"));

    const http = createHttpClient({ adapter });
    await expect(http.html("/fragment")).resolves.toBe("<div>ok</div>");

    const headers = AxiosHeaders.from(adapter.mock.calls[0]![0].headers);
    expect(headers.get("Accept")).toBe("text/html");
  });

  it("sends explicit accept header for json requests", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    await expect(http.getJson("/table")).resolves.toEqual({ ok: true });

    const headers = AxiosHeaders.from(adapter.mock.calls[0]![0].headers);
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("sends arbitrary JSON request methods", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    await expect(http.requestJson!("patch", "/users/42", { name: "Oldman" })).resolves.toEqual({ ok: true });

    expect(adapter.mock.calls[0]![0].method).toBe("patch");
    expect(adapter.mock.calls[0]![0].url).toBe("/users/42");
    expect(adapter.mock.calls[0]![0].data).toBe(JSON.stringify({ name: "Oldman" }));
  });

  it("includes the clicked submitter in form submissions", async () => {
    document.body.innerHTML = `
      <form>
        <input name="display_name" value="Alex">
        <button type="submit" name="intent" value="archive">Archive</button>
      </form>
    `;
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    const form = document.querySelector<HTMLFormElement>("form")!;
    const submitter = document.querySelector<HTMLButtonElement>("button")!;
    await http.postForm("/profile", form, undefined, submitter);

    const data = adapter.mock.calls[0]![0].data as FormData;
    expect(Array.from(data.entries())).toEqual([
      ["display_name", "Alex"],
      ["intent", "archive"]
    ]);
  });

  it("honors explicit accept header for form submissions", async () => {
    document.body.innerHTML = `
      <form>
        <input name="display_name" value="Alex">
      </form>
    `;
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    const form = document.querySelector<HTMLFormElement>("form")!;
    await http.postForm("/profile", form, { headers: { Accept: "text/html" } });

    const headers = AxiosHeaders.from(adapter.mock.calls[0]![0].headers);
    expect(headers.get("Accept")).toBe("text/html");
  });

  it("does not accept 422 for json forms", async () => {
    document.body.innerHTML = `
      <form>
        <input name="display_name" value="">
      </form>
    `;
    const payload = { error_code: 1100, errors: { display_name: "必填" } };
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      const result = { ...response(config, payload), status: 422 };
      const validateStatus = config.validateStatus ?? ((status: number) => status >= 200 && status < 300);
      if (!validateStatus(result.status)) {
        throw new AxiosError("Validation failed", "ERR_BAD_RESPONSE", config, {}, result);
      }
      return result;
    });

    const http = createHttpClient({ adapter });
    const form = document.querySelector<HTMLFormElement>("form")!;

    await expect(http.postForm("/profile", form, { headers: { Accept: "application/json" } })).rejects.toBeInstanceOf(AxiosError);
  });

  it("treats 422 html form responses as replaceable fragments", async () => {
    document.body.innerHTML = `
      <form>
        <input name="display_name" value="">
      </form>
    `;
    const html = `<form><input name="display_name" aria-invalid="true"></form>`;
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      const result = { ...response(config, html), status: 422 };
      const validateStatus = config.validateStatus ?? ((status: number) => status >= 200 && status < 300);
      if (!validateStatus(result.status)) {
        throw new AxiosError("Validation failed", "ERR_BAD_RESPONSE", config, {}, result);
      }
      return result;
    });

    const http = createHttpClient({ adapter });
    const form = document.querySelector<HTMLFormElement>("form")!;

    await expect(
      http.postForm("/profile", form, {
        headers: { Accept: "text/html" },
        responseType: "text",
        validateStatus: (status) => (status >= 200 && status < 300) || status === 422
      })
    ).resolves.toEqual({ data: html, status: 422 });
  });

  it("adds submitter fallback when FormData omits it", async () => {
    const NativeFormData = FormData;
    class FormDataWithoutSubmitter extends NativeFormData {
      constructor(form?: HTMLFormElement) {
        super(form);
      }
    }
    vi.stubGlobal("FormData", FormDataWithoutSubmitter);
    document.body.innerHTML = `
      <form>
        <input name="display_name" value="Alex">
        <button type="submit" name="intent" value="archive">Archive</button>
      </form>
    `;
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    const form = document.querySelector<HTMLFormElement>("form")!;
    const submitter = document.querySelector<HTMLButtonElement>("button")!;
    await http.postForm("/profile", form, undefined, submitter);

    const data = adapter.mock.calls[0]![0].data as FormData;
    expect(Array.from(data.entries())).toEqual([
      ["display_name", "Alex"],
      ["intent", "archive"]
    ]);
  });

  it("honors configured form request methods", async () => {
    document.body.innerHTML = `
      <form>
        <input name="display_name" value="Alex">
      </form>
    `;
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter });
    const form = document.querySelector<HTMLFormElement>("form")!;
    await http.postForm("/profile/archive", form, { method: "patch" });

    expect(adapter.mock.calls[0]![0].method).toBe("patch");
    expect(adapter.mock.calls[0]![0].url).toBe("/profile/archive");
    expect(adapter.mock.calls[0]![0].data).toBeInstanceOf(FormData);
  });

  it("attaches the default abort signal to requests", async () => {
    const controller = new AbortController();
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter, signal: controller.signal });
    await http.getJson("/slow");

    expect(adapter.mock.calls[0]![0].signal).toBe(controller.signal);
  });

  it("combines default and per-request abort signals", async () => {
    const defaultController = new AbortController();
    const requestController = new AbortController();
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter, signal: defaultController.signal });
    await http.getJson("/slow", { signal: requestController.signal });

    const signal = adapter.mock.calls[0]![0].signal as AbortSignal;
    expect(signal).not.toBe(defaultController.signal);
    expect(signal).not.toBe(requestController.signal);
    expect(signal.aborted).toBe(false);

    defaultController.abort();
    expect(signal.aborted).toBe(true);
  });

  it("aborts combined request signals when the per-request signal aborts", async () => {
    const defaultController = new AbortController();
    const requestController = new AbortController();
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { ok: true }));

    const http = createHttpClient({ adapter, signal: defaultController.signal });
    await http.getJson("/slow", { signal: requestController.signal });

    const signal = adapter.mock.calls[0]![0].signal as AbortSignal;
    requestController.abort();

    expect(signal.aborted).toBe(true);
  });

  it("normalizes axios errors and calls the optional error hook without replacing the rejection", async () => {
    let failure: AxiosError | undefined;
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      failure = new AxiosError("Forbidden", "ERR_BAD_REQUEST", config, {}, {
        data: { detail: "denied" },
        status: 403,
        statusText: "Forbidden",
        headers: {},
        config,
        request: {}
      });
      throw failure;
    });
    const onError = vi.fn();

    const http = createHttpClient({ adapter, onError });
    let rejected: unknown;
    try {
      await http.postJson("/admin", {});
    } catch (error) {
      rejected = error;
    }

    expect(rejected).toBe(failure);
    expect(onError).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledWith({
      data: { detail: "denied" },
      error: failure,
      isAxiosError: true,
      isCanceled: false,
      isNetworkError: false,
      method: "post",
      status: 403,
      url: "/admin"
    });
  });

  it("keeps the original request rejection when the error hook throws", async () => {
    const failure = new Error("network failed");
    const adapter = vi.fn<AxiosAdapter>(async () => {
      throw failure;
    });

    const http = createHttpClient({
      adapter,
      onError() {
        throw new Error("handler failed");
      }
    });

    await expect(http.getJson("/status")).rejects.toBe(failure);
  });

  it("adds the visible page as next for a 401 authentication response", async () => {
    window.history.replaceState({}, "", "/users?page=2#row");
    let failure: AxiosError | undefined;
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      failure = new AxiosError("Authentication required", "ERR_BAD_REQUEST", config, {}, {
        data: { error_code: 1401, data: { login_url: "/login" }, actions: [] },
        status: 401,
        statusText: "Unauthorized",
        headers: {},
        config,
        request: {}
      });
      throw failure;
    });
    const onAuthRedirect = vi.fn();

    const http = createHttpClient({ adapter, onAuthRedirect });
    await expect(http.getJson("/users")).rejects.toBeInstanceOf(AxiosError);
    expect(failure).toBeInstanceOf(AxiosError);

    expect(onAuthRedirect).toHaveBeenCalledWith("/login?next=%2Fusers%3Fpage%3D2%23row");
  });

  it("falls back to login when 401 auth response omits redirect url", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      throw new AxiosError("Authentication required", "ERR_BAD_REQUEST", config, {}, {
        data: { error_code: 1401 },
        status: 401,
        statusText: "Unauthorized",
        headers: {},
        config,
        request: {}
      });
    });
    const onAuthRedirect = vi.fn();

    const http = createHttpClient({ adapter, onAuthRedirect });
    await expect(http.getJson("/users")).rejects.toBeInstanceOf(AxiosError);

    expect(onAuthRedirect).toHaveBeenCalledWith("/login?next=%2F");
  });

  it("does not call auth redirect handler for 403 responses", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      throw new AxiosError("Forbidden", "ERR_BAD_REQUEST", config, {}, {
        data: { error_code: 1403 },
        status: 403,
        statusText: "Forbidden",
        headers: {},
        config,
        request: {}
      });
    });
    const onAuthRedirect = vi.fn();

    const http = createHttpClient({ adapter, onAuthRedirect });
    await expect(http.getJson("/users")).rejects.toBeInstanceOf(AxiosError);

    expect(onAuthRedirect).not.toHaveBeenCalled();
  });

  it("allows background requests to leave authentication navigation to their owner", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      throw new AxiosError("Authentication required", "ERR_BAD_REQUEST", config, {}, {
        data: { error_code: 1401, data: { login_url: "/login" } },
        status: 401,
        statusText: "Unauthorized",
        headers: {},
        config,
        request: {}
      });
    });
    const onAuthRedirect = vi.fn();
    const http = createHttpClient({ adapter, onAuthRedirect });

    await expect(http.html("/notifications", { redirectOnAuth: false })).rejects.toBeInstanceOf(AxiosError);

    expect(onAuthRedirect).not.toHaveBeenCalled();
  });

  it("parses a 401 text body only when its content type is json", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      throw new AxiosError("Authentication required", "ERR_BAD_REQUEST", config, {}, {
        data: JSON.stringify({ error_code: 1401, data: { login_url: "/login" }, actions: [] }),
        status: 401,
        statusText: "Unauthorized",
        headers: { "content-type": "application/json; charset=utf-8" },
        config,
        request: {}
      });
    });
    const onAuthRedirect = vi.fn();

    const http = createHttpClient({ adapter, onAuthRedirect });
    await expect(http.html("/dashboard")).rejects.toBeInstanceOf(AxiosError);

    expect(onAuthRedirect).toHaveBeenCalledWith("/login?next=%2F");
  });

  it("skips the ordinary error hook for authentication redirects and cancellation", async () => {
    const authAdapter = vi.fn<AxiosAdapter>(async (config) => {
      throw new AxiosError("Authentication required", "ERR_BAD_REQUEST", config, {}, {
        data: { error_code: 1401, data: { login_url: "/login" }, actions: [] },
        status: 401,
        statusText: "Unauthorized",
        headers: {},
        config,
        request: {}
      });
    });
    const onError = vi.fn();
    const http = createHttpClient({ adapter: authAdapter, onAuthRedirect: vi.fn(), onError });

    await expect(http.getJson("/private")).rejects.toBeInstanceOf(AxiosError);
    expect(onError).not.toHaveBeenCalled();

    const canceled = new CanceledError("canceled");
    const canceledHttp = createHttpClient({
      adapter: vi.fn<AxiosAdapter>(async () => { throw canceled; }),
      onError
    });
    await expect(canceledHttp.getJson("/slow")).rejects.toBe(canceled);
    expect(onError).not.toHaveBeenCalled();
  });

  it("normalizes non-axios errors", () => {
    const failure = new Error("plain");

    expect(normalizeHttpError(failure)).toEqual({
      error: failure,
      isAxiosError: false,
      isCanceled: false,
      isNetworkError: false
    });
  });
});
