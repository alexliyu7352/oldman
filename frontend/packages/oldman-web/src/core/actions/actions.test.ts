import { describe, expect, it, vi } from "vitest";
import type { AxiosRequestConfig } from "axios";
import { Page } from "../page/page";
import { PageRegistry } from "../page/registry";
import { TransitionService } from "../services/transitions";
import {
  runAction as runCoreAction,
  startActions as startCoreActions,
  type RunActionOptions,
  type StartActionsOptions
} from "./actions";
import type { DefaultApiResponse } from "./response-actions";
import type { HttpClient } from "../http/client";

class ActionTestPage extends Page {}

class StaticPageRegistry extends PageRegistry {
  private readonly page: Page;

  constructor(root: HTMLElement) {
    super();
    this.page = new ActionTestPage(root);
  }

  override get current(): Page {
    return this.page;
  }
}

function runAction(
  trigger: HTMLElement,
  options: Omit<RunActionOptions, "pageRegistry">
): Promise<DefaultApiResponse | null> {
  return runCoreAction(trigger, {
    ...options,
    pageRegistry: new StaticPageRegistry(pageRoot(options.root))
  });
}

function startActions(options: Omit<StartActionsOptions, "pageRegistry">): () => void {
  return startCoreActions({
    ...options,
    pageRegistry: new StaticPageRegistry(pageRoot(options.root))
  });
}

function pageRoot(root: Document | HTMLElement | undefined): HTMLElement {
  return root instanceof HTMLElement ? root : document.body;
}

function apiResponse(html: string): DefaultApiResponse {
  return {
    error_code: 0,
    message: "",
    data: {},
    actions: [{ action: "replace_html", html }]
  };
}

function createHttp(html: string): HttpClient {
  return {
    axios: {} as HttpClient["axios"],
    getJson: vi.fn(),
    postJson: async <T>() => apiResponse(html) as T,
    html: vi.fn(),
    postForm: vi.fn()
  };
}

function createEmptyHttp(overrides: Partial<HttpClient> = {}): HttpClient {
  return {
    axios: {} as HttpClient["axios"],
    getJson: vi.fn(),
    postJson: vi.fn(),
    html: vi.fn(),
    postForm: vi.fn(),
    ...overrides
  };
}

function submitForm(form: HTMLFormElement, submitter?: HTMLElement): Event {
  const event =
    typeof SubmitEvent === "function"
      ? new SubmitEvent("submit", {
          bubbles: true,
          cancelable: true,
          ...(submitter ? { submitter } : {})
        })
      : new Event("submit", { bubbles: true, cancelable: true });
  if (submitter && !("submitter" in event)) {
    Object.defineProperty(event, "submitter", {
      configurable: true,
      value: submitter
    });
  }
  form.dispatchEvent(event);
  return event;
}

describe("startActions", () => {
  it("owns declarative form submissions before Turbo Frame interception and releases the listener", async () => {
    // jsdom lacks layout observation; real Turbo still owns form interception.
    vi.stubGlobal("IntersectionObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    const Turbo = await import("@hotwired/turbo");
    Turbo.start();
    document.body.innerHTML = `
      <turbo-frame id="action-frame">
        <form action="/save" method="post" data-om-action="post" data-om-target="#result">
          <button type="submit">Save</button>
        </form>
        <div id="result">old</div>
      </turbo-frame>
    `;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const fetched = vi.fn((event: Event) => event.preventDefault());
    const http = createHttp("new");
    const posted = vi.spyOn(http, "postJson");
    form.addEventListener("turbo:before-fetch-request", fetched);
    const stop = startActions({ http });
    try {
      expect(submitForm(form).defaultPrevented).toBe(true);
      await vi.waitFor(() => expect(document.querySelector("#result")!.textContent).toBe("new"));
      expect(posted).toHaveBeenCalledOnce();
      expect(fetched).not.toHaveBeenCalled();

      // A component may require its own confirmation before using runAction.
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        event.stopPropagation();
      }, { once: true });
      submitForm(form);
      await Promise.resolve();
      expect(posted).toHaveBeenCalledOnce();

      stop();
      // No Oldman listener survives cleanup; a native submission is untouched.
      form.setAttribute("data-turbo", "false");
      expect(submitForm(form).defaultPrevented).toBe(false);
      expect(posted).toHaveBeenCalledOnce();
    } finally {
      stop();
      document.body.replaceChildren();
      (Turbo.session as unknown as { stop(): void }).stop();
      vi.unstubAllGlobals();
    }
  });

  it("runs actions programmatically with the same lifecycle", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/disable" data-om-target="#row" data-om-swap="outer">Disable</button>
      <div id="row">old</div>
    `;
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const success = vi.fn();
    const complete = vi.fn();
    button.addEventListener("om:action:success", success);
    button.addEventListener("om:action:complete", complete);

    const response = await runAction(button, {
      http: createHttp("<div id=\"row\">new</div>")
    });

    expect(response).toEqual(apiResponse("<div id=\"row\">new</div>"));
    expect(document.querySelector("#row")!.textContent).toBe("new");
    expect(button.dataset.omLoading).toBeUndefined();
    expect(button.getAttribute("aria-busy")).toBe("false");
    expect(success).toHaveBeenCalledOnce();
    expect(complete).toHaveBeenCalledOnce();
    expect((success.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail).toEqual({
      method: "post",
      params: {},
      response: apiResponse("<div id=\"row\">new</div>"),
      trigger: button,
      url: "/disable"
    });
    expect((complete.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail).toEqual({
      method: "post",
      params: {},
      response: apiResponse("<div id=\"row\">new</div>"),
      trigger: button,
      url: "/disable"
    });
  });

  it("posts and swaps target outer html", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/disable" data-om-target="#row" data-om-swap="outer">Disable</button>
      <div id="row">old</div>
    `;

    const cleanup = startActions({ http: createHttp("<div id=\"row\">new</div>") });
    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("new");
    });
    cleanup();
  });

  it("follows ordered redirect response actions", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/save">Save</button>
    `;
    const originalLocation = window.location;
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, assign }
    });
    const button = document.querySelector<HTMLButtonElement>("button")!;

    try {
      await runAction(button, {
        http: createEmptyHttp({
          requestJson: async <T>() => ({
            error_code: 0,
            message: "",
            data: {},
            actions: [{ action: "redirect", url: "/dashboard" }]
          }) as T
        })
      });

      expect(assign).toHaveBeenCalledWith("/dashboard");
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation
      });
    }
  });

  it("toggles local DOM targets without sending HTTP", async () => {
    document.body.innerHTML = `
      <button
        data-om-action="toggle"
        data-om-target="#filters"
        data-om-toggle-class="is-open"
        data-om-toggle-trigger-class="is-active"
        aria-expanded="false"
      >
        Toggle filters
      </button>
      <section id="filters" hidden></section>
    `;
    const http = createEmptyHttp();
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const target = document.querySelector<HTMLElement>("#filters")!;
    const toggle = vi.fn();
    button.addEventListener("om:action:toggle", toggle);
    const cleanup = startActions({ http });
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });

    button.dispatchEvent(event);

    await vi.waitFor(() => {
      expect(target.getAttribute("aria-hidden")).toBe("false");
    });

    expect(event.defaultPrevented).toBe(true);
    expect(http.postJson).not.toHaveBeenCalled();
    expect(target.hidden).toBe(false);
    expect(target.classList.contains("is-open")).toBe(true);
    expect(button.classList.contains("is-active")).toBe(true);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(button.getAttribute("aria-controls")).toBe("filters");
    expect(toggle).toHaveBeenCalledOnce();
    expect((toggle.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail).toEqual({
      target,
      trigger: button,
      visible: true
    });

    button.click();
    await vi.waitFor(() => {
      expect(target.hidden).toBe(true);
    });

    expect(target.getAttribute("aria-hidden")).toBe("true");
    expect(target.classList.contains("is-open")).toBe(false);
    expect(button.classList.contains("is-active")).toBe(false);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    cleanup();
  });

  it("runs show and hide toggle actions programmatically", async () => {
    document.body.innerHTML = `
      <button data-om-action="toggle" data-om-toggle="show" data-om-target="#panel">Show</button>
      <button data-om-action="toggle" data-om-toggle="hide" data-om-target="#panel">Hide</button>
      <section id="panel" hidden></section>
    `;
    const panel = document.querySelector<HTMLElement>("#panel")!;
    const show = document.querySelector<HTMLButtonElement>("[data-om-toggle='show']")!;
    const hide = document.querySelector<HTMLButtonElement>("[data-om-toggle='hide']")!;

    await runAction(show, { http: createEmptyHttp() });
    expect(panel.hidden).toBe(false);
    expect(show.getAttribute("aria-expanded")).toBe("true");

    await runAction(hide, { http: createEmptyHttp() });
    expect(panel.hidden).toBe(true);
    expect(hide.getAttribute("aria-expanded")).toBe("false");
  });

  it("dispatches the HTTP method from data-om-action", async () => {
    document.body.innerHTML = `
      <button data-om-action="delete" data-om-url="/users/42" data-om-target="#row" data-om-swap="outer">Delete</button>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">deleted</div>") as T;
    };
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("deleted");
    });

    expect(requestJsonCalls).toEqual([["delete", "/users/42", undefined, expect.any(Object)]]);
    cleanup();
  });

  it("uses refresh actions as GET API requests", async () => {
    document.body.innerHTML = `
      <form id="filters">
        <input name="q" value="alex">
      </form>
      <button data-om-action="refresh" data-om-url="/users" data-om-include="#filters" data-om-target="#row">
        Refresh
      </button>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">refreshed</div>") as T;
    };
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("refreshed");
    });

    const [method, url, data, config] = requestJsonCalls[0]!;
    expect(method).toBe("get");
    expect(url).toBe("/users");
    expect(data).toBeUndefined();
    expect(Array.from((config as { params: URLSearchParams }).params.entries())).toEqual([["q", "alex"]]);
    cleanup();
  });

  it("dispatches request before sending action HTTP", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/users" data-om-target="#row">Save</button>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">new</div>") as T;
    };
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const request = vi.fn((_event: Event) => {
      expect(requestJsonCalls).toHaveLength(0);
    });
    button.addEventListener("om:action:request", request);

    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("new");
    });

    expect(request).toHaveBeenCalledOnce();
    expect((request.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail).toEqual({
      method: "post",
      params: {},
      trigger: button,
      url: "/users"
    });
    expect(requestJsonCalls).toEqual([["post", "/users", {}, expect.any(Object)]]);
    cleanup();
  });

  it("lets request listeners add action params before sending HTTP", async () => {
    document.body.innerHTML = `
      <form id="filters">
        <input name="role" value="admin">
      </form>
      <button data-om-action="post" data-om-include="#filters" data-om-url="/users" data-om-target="#row">
        Save
      </button>
      <div id="row">old</div>
    `;
    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">new</div>") as T;
    };
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const request = vi.fn((event: Event) => {
      const detail = (event as CustomEvent).detail as { params: Record<string, string | string[]> };
      detail.params.page = "2";
      detail.params.scope = ["active", "invited"];
    });
    button.addEventListener("om:action:request", request);

    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("new");
    });

    expect(request).toHaveBeenCalledOnce();
    expect((request.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail.params).toEqual({
      role: "admin",
      page: "2",
      scope: ["active", "invited"]
    });
    const [_method, _url, data] = requestJsonCalls[0]!;
    expect(data).toBeInstanceOf(FormData);
    expect(Array.from((data as FormData).entries())).toEqual([
      ["role", "admin"],
      ["page", "2"],
      ["scope", "active"],
      ["scope", "invited"]
    ]);
    cleanup();
  });

  it("uses native link href as the action URL", async () => {
    document.body.innerHTML = `
      <a data-om-action="get" href="/users/42" data-om-target="#row" data-om-swap="outer">View</a>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">viewed</div>") as T;
    };
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    document.querySelector("a")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("viewed");
    });

    expect(requestJsonCalls).toEqual([["get", "/users/42", undefined, expect.any(Object)]]);
    cleanup();
  });

  it("uses button formaction or form action as the action URL and submits owning form data", async () => {
    document.body.innerHTML = `
      <form action="/users">
        <input name="display_name" value="Alex">
        <button
          data-om-action="patch"
          formaction="/users/42"
          name="intent"
          value="save"
          data-om-target="#row"
          data-om-swap="outer"
        >
          Save
        </button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">saved</div>") as T;
    };
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("saved");
    });

    const [method, url, data, config] = requestJsonCalls[0]!;
    expect(method).toBe("patch");
    expect(url).toBe("/users/42");
    expect(data).toBeInstanceOf(FormData);
    expect(Array.from((data as FormData).entries())).toEqual([
      ["display_name", "Alex"],
      ["intent", "save"]
    ]);
    expect(config).toEqual(expect.any(Object));
    cleanup();
  });

  it("submits forms that declare data-om-action directly", async () => {
    document.body.innerHTML = `
      <form data-om-action="post" action="/users" data-om-target="#row">
        <input name="display_name" value="Alex">
        <button name="intent" value="save">Save</button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">created</div>") as T;
    };
    const form = document.querySelector<HTMLFormElement>("form")!;
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const request = vi.fn();
    form.addEventListener("om:action:request", request);
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    const event = submitForm(form, button);

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("created");
    });

    expect(event.defaultPrevented).toBe(true);
    const [method, url, data] = requestJsonCalls[0]!;
    expect(method).toBe("post");
    expect(url).toBe("/users");
    expect(data).toBeInstanceOf(FormData);
    expect(Array.from((data as FormData).entries())).toEqual([
      ["display_name", "Alex"],
      ["intent", "save"]
    ]);
    expect((request.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail).toEqual({
      method: "post",
      params: {},
      submitter: button,
      trigger: form,
      url: "/users"
    });
    cleanup();
  });

  it("uses submit events for direct form action button clicks", async () => {
    document.body.innerHTML = `
      <form data-om-action="post" action="/users" data-om-target="#row">
        <input name="display_name" value="Alex">
        <button name="intent" value="save">Save</button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">created</div>") as T;
    };
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("created");
    });

    expect(requestJsonCalls).toHaveLength(1);
    const [method, url, data] = requestJsonCalls[0]!;
    expect(method).toBe("post");
    expect(url).toBe("/users");
    expect(Array.from((data as FormData).entries())).toEqual([
      ["display_name", "Alex"],
      ["intent", "save"]
    ]);
    cleanup();
  });

  it("uses form method for submit actions", async () => {
    document.body.innerHTML = `
      <form data-om-action="submit" method="post" action="/users" data-om-target="#row">
        <input name="display_name" value="Alex">
        <button name="intent" value="save">Save</button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">created</div>") as T;
    };
    const form = document.querySelector<HTMLFormElement>("form")!;
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    submitForm(form, button);

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("created");
    });

    const [method, url, data] = requestJsonCalls[0]!;
    expect(method).toBe("post");
    expect(url).toBe("/users");
    expect(data).toBeInstanceOf(FormData);
    expect(Array.from((data as FormData).entries())).toEqual([
      ["display_name", "Alex"],
      ["intent", "save"]
    ]);
    cleanup();
  });

  it("uses submitter overrides for direct form actions", async () => {
    document.body.innerHTML = `
      <form data-om-action="post" action="/users" data-om-target="#row">
        <input name="display_name" required>
        <button name="intent" value="draft" formaction="/users/draft" formmethod="get" formnovalidate>
          Preview draft
        </button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">draft</div>") as T;
    };
    const form = document.querySelector<HTMLFormElement>("form")!;
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    submitForm(form, button);

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("draft");
    });

    const [method, url, data, config] = requestJsonCalls[0]!;
    expect(method).toBe("get");
    expect(url).toBe("/users/draft");
    expect(data).toBeUndefined();
    expect(Array.from((config as { params: URLSearchParams }).params.entries())).toEqual([
      ["display_name", ""],
      ["intent", "draft"]
    ]);
    cleanup();
  });

  it("does not run invalid owning form actions before confirmation", async () => {
    document.body.innerHTML = `
      <form action="/users" data-om-confirm="ignored">
        <input name="display_name" required>
        <button
          data-om-action="post"
          data-om-confirm="Save?"
          data-om-target="#row"
        >
          Save
        </button>
      </form>
      <div id="row">old</div>
    `;

    const http = createEmptyHttp();
    const confirm = vi.fn(() => true);
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const input = document.querySelector<HTMLInputElement>("input")!;
    const invalid = vi.fn();
    const complete = vi.fn();
    button.addEventListener("om:action:invalid", invalid);
    button.addEventListener("om:action:complete", complete);

    const cleanup = startActions({ http, confirm });
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

    await Promise.resolve();

    expect(invalid).toHaveBeenCalledOnce();
    expect((invalid.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail).toEqual({
      controls: [input],
      form: document.querySelector("form"),
      method: "post",
      trigger: button,
      url: "/users"
    });
    expect(complete).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    expect(http.postJson).not.toHaveBeenCalled();
    expect(button.dataset.omLoading).toBeUndefined();
    expect(document.querySelector("#row")!.textContent).toBe("old");
    cleanup();
  });

  it("allows action validation to be skipped explicitly", async () => {
    document.body.innerHTML = `
      <form action="/users">
        <input name="display_name" required>
        <button data-om-action="post" data-om-target="#row">Save</button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">saved</div>") as T;
    };
    const button = document.querySelector<HTMLButtonElement>("button")!;

    await runAction(button, {
      http: createEmptyHttp({ requestJson }),
      validate: false
    });

    expect(requestJsonCalls).toHaveLength(1);
    expect(document.querySelector("#row")!.textContent).toBe("saved");
  });

  it("respects native formnovalidate on action submitters", async () => {
    document.body.innerHTML = `
      <form action="/users">
        <input name="display_name" required>
        <button data-om-action="post" data-om-target="#row" formnovalidate>Save draft</button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">draft</div>") as T;
    };
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("draft");
    });
    expect(requestJsonCalls).toHaveLength(1);
    cleanup();
  });

  it("uses form-level confirmation for owning form actions", async () => {
    document.body.innerHTML = `
      <form action="/users" data-om-confirm="Save user?">
        <input name="display_name" value="Alex">
        <button data-om-action="post" data-om-target="#row">Save</button>
      </form>
      <div id="row">old</div>
    `;

    const http = createEmptyHttp();
    const confirm = vi.fn(() => false);
    const cleanup = startActions({ http, confirm });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    await Promise.resolve();

    expect(confirm).toHaveBeenCalledWith("Save user?");
    expect(http.postJson).not.toHaveBeenCalled();
    expect(document.querySelector("#row")!.textContent).toBe("old");
    cleanup();
  });

  it("waits for async confirmations before running owning form actions", async () => {
    document.body.innerHTML = `
      <form action="/users" data-om-confirm="Save user?">
        <input name="display_name" value="Alex">
        <button data-om-action="post" data-om-target="#row">Save</button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">saved</div>") as T;
    };
    let allowConfirm: (value: boolean) => void = () => {};
    const confirm = vi.fn(() => new Promise<boolean>((resolve) => {
      allowConfirm = resolve;
    }));
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }), confirm });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    await Promise.resolve();

    expect(confirm).toHaveBeenCalledWith("Save user?");
    expect(requestJsonCalls).toHaveLength(0);

    allowConfirm(true);

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("saved");
    });
    expect(requestJsonCalls).toHaveLength(1);
    cleanup();
  });

  it("prefers action trigger confirmation over form confirmation", async () => {
    document.body.innerHTML = `
      <form action="/users" data-om-confirm="Save user?">
        <input name="display_name" value="Alex">
        <button data-om-action="post" data-om-confirm="Archive user?" data-om-target="#row">Archive</button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">archived</div>") as T;
    };
    const confirm = vi.fn(() => true);
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }), confirm });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("archived");
    });
    expect(confirm).toHaveBeenCalledWith("Archive user?");
    expect(confirm).not.toHaveBeenCalledWith("Save user?");
    expect(requestJsonCalls).toHaveLength(1);
    cleanup();
  });

  it("sends owning form data as query params for get actions", async () => {
    document.body.innerHTML = `
      <form action="/users">
        <input name="q" value="alex">
        <button
          data-om-action="get"
          name="page"
          value="2"
          data-om-target="#row"
          data-om-swap="outer"
        >
          Search
        </button>
      </form>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">results</div>") as T;
    };
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("results");
    });

    const [method, url, data, config] = requestJsonCalls[0]!;
    expect(method).toBe("get");
    expect(url).toBe("/users");
    expect(data).toBeUndefined();
    expect(Array.from(((config as AxiosRequestConfig).params as URLSearchParams).entries())).toEqual([
      ["q", "alex"],
      ["page", "2"]
    ]);
    cleanup();
  });

  it("includes selected form params for get actions", async () => {
    document.body.innerHTML = `
      <form id="filters">
        <input name="q" value="alex">
        <input type="checkbox" name="role" value="admin" checked>
        <input type="checkbox" name="role" value="guest">
      </form>
      <a data-om-action="get" data-om-include="#filters" href="/users" data-om-target="#row">Refresh</a>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">filtered</div>") as T;
    };
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    document.querySelector("a")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("filtered");
    });

    const [_method, _url, data, config] = requestJsonCalls[0]!;
    expect(data).toBeUndefined();
    expect(Array.from(((config as AxiosRequestConfig).params as URLSearchParams).entries())).toEqual([
      ["q", "alex"],
      ["role", "admin"]
    ]);
    cleanup();
  });

  it("includes selected form params in state-changing action bodies", async () => {
    document.body.innerHTML = `
      <form id="filters">
        <input name="q" value="alex">
        <select name="role" multiple>
          <option value="admin" selected>Admin</option>
          <option value="staff" selected>Staff</option>
        </select>
      </form>
      <button data-om-action="post" data-om-include="#filters" data-om-url="/export" data-om-target="#row">
        Export
      </button>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">exported</div>") as T;
    };
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("exported");
    });

    const [_method, _url, data] = requestJsonCalls[0]!;
    expect(data).toBeInstanceOf(FormData);
    expect(Array.from((data as FormData).entries())).toEqual([
      ["q", "alex"],
      ["role", "admin"],
      ["role", "staff"]
    ]);
    cleanup();
  });

  it("lets page scripts pass explicit action params", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/users" data-om-target="#row">Refresh</button>
      <div id="row">old</div>
    `;

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return apiResponse("<div id=\"row\">new</div>") as T;
    };
    const button = document.querySelector<HTMLButtonElement>("button")!;

    await runAction(button, {
      http: createEmptyHttp({ requestJson }),
      params: {
        page: "2",
        role: ["admin", "staff"]
      }
    });

    const [_method, _url, data] = requestJsonCalls[0]!;
    expect(data).toBeInstanceOf(FormData);
    expect(Array.from((data as FormData).entries())).toEqual([
      ["page", "2"],
      ["role", "admin"],
      ["role", "staff"]
    ]);
    expect(document.querySelector("#row")!.textContent).toBe("new");
  });

  it("scopes local target swaps to the configured root", async () => {
    document.body.innerHTML = `
      <section id="outside">
        <button data-om-action="post" data-om-url="/outside" data-om-target=".row" data-om-swap="inner">Outside</button>
        <div class="row">outside</div>
      </section>
      <section id="inside">
        <button data-om-action="post" data-om-url="/inside" data-om-target=".row" data-om-swap="inner">Inside</button>
        <div class="row">inside</div>
      </section>
    `;

    const cleanup = startActions({
      http: createHttp("<span>new</span>"),
      root: document.querySelector("#inside") as HTMLElement
    });

    document.querySelector("#inside button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#inside .row")!.innerHTML).toBe("<span>new</span>");
    });

    expect(document.querySelector("#outside .row")!.textContent).toBe("outside");
    cleanup();
  });

  it("marks the trigger as loading and ignores duplicate clicks while pending", async () => {
    document.body.innerHTML = `
      <input id="filter" name="q" value="alex">
      <button id="secondary" type="button">Secondary</button>
      <button id="locked" type="button" disabled>Locked</button>
      <button
        data-om-action="post"
        data-om-url="/disable"
        data-om-target="#row"
        data-om-swap="outer"
        data-om-loading-class="is-loading text-muted"
        data-om-disable="#filter, #secondary, #locked"
      >
        Disable
      </button>
      <div id="row">old</div>
    `;

    let postCalls = 0;
    let resolveResponse: ((value: DefaultApiResponse) => void) | undefined;
    const postJson: HttpClient["postJson"] = async <T>() => {
      postCalls += 1;
      return new Promise<T>((resolve) => {
        resolveResponse = (value) => resolve(value as T);
      });
    };
    const http: HttpClient = {
      axios: {} as HttpClient["axios"],
      getJson: vi.fn(),
      postJson,
      html: vi.fn(),
      postForm: vi.fn()
    };

    const cleanup = startActions({ http });
    const button = document.querySelector<HTMLButtonElement>("[data-om-action]")!;
    const filter = document.querySelector<HTMLInputElement>("#filter")!;
    const secondary = document.querySelector<HTMLButtonElement>("#secondary")!;
    const locked = document.querySelector<HTMLButtonElement>("#locked")!;
    const success = vi.fn();
    const complete = vi.fn();
    button.addEventListener("om:action:success", success);
    button.addEventListener("om:action:complete", complete);

    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(button.dataset.omLoading).toBe("true");
    });

    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.disabled).toBe(true);
    expect(button.classList.contains("is-loading")).toBe(true);
    expect(button.classList.contains("text-muted")).toBe(true);
    expect(filter.disabled).toBe(true);
    expect(secondary.disabled).toBe(true);
    expect(locked.disabled).toBe(true);

    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(postCalls).toBe(1);

    resolveResponse?.(apiResponse("<div id=\"row\">new</div>"));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.textContent).toBe("new");
    });

    await vi.waitFor(() => {
      expect(button.dataset.omLoading).toBeUndefined();
      expect(button.getAttribute("aria-busy")).toBe("false");
      expect(button.disabled).toBe(false);
      expect(button.classList.contains("is-loading")).toBe(false);
      expect(button.classList.contains("text-muted")).toBe(false);
      expect(filter.disabled).toBe(false);
      expect(secondary.disabled).toBe(false);
      expect(locked.disabled).toBe(true);
      expect(success).toHaveBeenCalledOnce();
      expect(complete).toHaveBeenCalledOnce();
    });

    const successEvent = success.mock.calls[0]?.[0] as CustomEvent | undefined;
    const completeEvent = complete.mock.calls[0]?.[0] as CustomEvent | undefined;
    expect(successEvent?.detail.response).toEqual(apiResponse("<div id=\"row\">new</div>"));
    expect(completeEvent?.detail.response).toEqual(apiResponse("<div id=\"row\">new</div>"));
    expect(successEvent?.detail.trigger).toBe(button);
    expect(successEvent?.detail.method).toBe("post");
    expect(successEvent?.detail.url).toBe("/disable");
    expect(completeEvent?.detail.trigger).toBe(button);
    expect(completeEvent?.detail.method).toBe("post");
    expect(completeEvent?.detail.url).toBe("/disable");
    cleanup();
  });

  it("refreshes actions on an interval and clears timers when stopped", async () => {
    vi.useFakeTimers();
    try {
      document.body.innerHTML = `
        <button
          data-om-action="refresh"
          data-om-refresh-interval="1000"
          data-om-url="/stats"
          data-om-target="#stats"
        >
          Refresh
        </button>
        <div id="stats">old</div>
      `;

      let refreshCount = 0;
      const requestJsonCalls: unknown[][] = [];
      const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
        requestJsonCalls.push(args);
        refreshCount += 1;
        return apiResponse(`<div id="stats">${refreshCount}</div>`) as T;
      };
      const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

      expect(requestJsonCalls).toHaveLength(0);

      await vi.advanceTimersByTimeAsync(1000);
      expect(document.querySelector("#stats")!.textContent).toBe("1");

      await vi.advanceTimersByTimeAsync(1000);
      expect(document.querySelector("#stats")!.textContent).toBe("2");
      expect(requestJsonCalls.map(([method, url]) => [method, url])).toEqual([
        ["get", "/stats"],
        ["get", "/stats"]
      ]);

      cleanup();
      await vi.advanceTimersByTimeAsync(2000);
      expect(requestJsonCalls).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("marks failed actions as errored and dispatches lifecycle events", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/disable" data-om-target="#row" data-om-swap="outer">Disable</button>
      <div id="row">old</div>
    `;

    const failure = new Error("request failed");
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const http: HttpClient = {
      axios: {} as HttpClient["axios"],
      getJson: vi.fn(),
      postJson: async () => {
        throw failure;
      },
      html: vi.fn(),
      postForm: vi.fn()
    };

    const cleanup = startActions({ http });
    const button = document.querySelector("button") as HTMLButtonElement;
    const error = vi.fn();
    const complete = vi.fn();
    button.addEventListener("om:action:error", error);
    button.addEventListener("om:action:complete", complete);

    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(button.dataset.omError).toBe("true");
    });

    expect(button.dataset.omLoading).toBeUndefined();
    expect(button.getAttribute("aria-busy")).toBe("false");
    expect(button.disabled).toBe(false);
    expect(error).toHaveBeenCalledOnce();
    expect(complete).toHaveBeenCalledOnce();
    const errorEvent = error.mock.calls[0]?.[0] as CustomEvent | undefined;
    const completeEvent = complete.mock.calls[0]?.[0] as CustomEvent | undefined;
    expect(errorEvent?.detail.error).toBe(failure);
    expect(completeEvent?.detail.error).toBe(failure);
    expect(errorEvent?.detail.trigger).toBe(button);
    expect(errorEvent?.detail.method).toBe("post");
    expect(errorEvent?.detail.url).toBe("/disable");
    expect(completeEvent?.detail.trigger).toBe(button);
    expect(completeEvent?.detail.method).toBe("post");
    expect(completeEvent?.detail.url).toBe("/disable");
    expect(document.querySelector("#row")!.textContent).toBe("old");
    expect(logged).toHaveBeenCalledWith("Oldman response action failed", failure);
    logged.mockRestore();
    cleanup();
  });

  it("shows the current Page feedback when a remote request fails", async () => {
    document.body.innerHTML = `
      <main id="page"><button data-om-action="post" data-om-url="/save">Save</button></main>
    `;
    const root = document.querySelector<HTMLElement>("#page")!;
    const button = root.querySelector<HTMLButtonElement>("button")!;
    const page = new ActionTestPage(root);
    const alert = vi.fn().mockResolvedValue({});
    page.feedback = { alert, close: vi.fn(), toast: vi.fn() };
    const pageRegistry = { current: page } as PageRegistry;
    const failure = new Error("server unavailable");

    await runCoreAction(button, {
      http: createEmptyHttp({ postJson: vi.fn().mockRejectedValue(failure) }),
      pageRegistry
    });

    expect(alert).toHaveBeenCalledWith({ icon: "error", titleText: "Request failed" });
    expect(button.dataset.omError).toBe("true");
  });

  it("dispatches configured success events after applying updates", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/refresh" data-om-event-success="users:refreshed">
        Refresh
      </button>
      <div id="notice">old</div>
    `;
    const response: DefaultApiResponse = {
      error_code: 0,
      message: "",
      data: {},
      actions: [{ action: "replace_html", target: "#notice", html: "updated" }]
    };
    const requestJson: NonNullable<HttpClient["requestJson"]> = async <T>() => response as T;
    const button = document.querySelector<HTMLButtonElement>("button")!;
    const success = vi.fn();
    const refreshed = vi.fn((event: Event) => {
      expect(document.querySelector("#notice")!.textContent).toBe("updated");
      expect((event as CustomEvent).detail.response).toEqual(response);
    });
    button.addEventListener("om:action:success", success);
    document.addEventListener("users:refreshed", refreshed);
    const cleanup = startActions({ http: createEmptyHttp({ requestJson }) });

    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(refreshed).toHaveBeenCalledOnce();
    });

    expect(success).toHaveBeenCalledOnce();
    expect((refreshed.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail).toMatchObject({
      method: "post",
      params: {},
      trigger: button,
      url: "/refresh"
    });
    document.removeEventListener("users:refreshed", refreshed);
    cleanup();
  });

  it("aborts active action requests when stopped without applying stale responses", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/disable" data-om-target="#row" data-om-swap="outer">Disable</button>
      <div id="row">old</div>
    `;

    let signal: AbortSignal | undefined;
    let resolveResponse: ((value: DefaultApiResponse) => void) | undefined;
    const postJson: HttpClient["postJson"] = async <T>(
      _url: string,
      _data?: unknown,
      config?: AxiosRequestConfig
    ) => {
      signal = config?.signal as AbortSignal | undefined;
      return new Promise<T>((resolve, reject) => {
        resolveResponse = (value) => resolve(value as T);
        signal?.addEventListener("abort", () => reject(new Error("aborted")));
      });
    };
    const http: HttpClient = {
      axios: {} as HttpClient["axios"],
      getJson: vi.fn(),
      postJson,
      html: vi.fn(),
      postForm: vi.fn()
    };

    const cleanup = startActions({ http });
    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(signal).toBeDefined();
    });

    cleanup();
    cleanup();
    resolveResponse?.(apiResponse("<div id=\"row\">new</div>"));
    await Promise.resolve();

    expect(signal?.aborted).toBe(true);
    expect(document.querySelector("#row")!.textContent).toBe("old");
  });

});
