import { afterEach, describe, expect, it, vi } from "vitest";
import { Page } from "../page/page";
import {
  ApiResponseAction,
  ResponseActionRunner,
  type DefaultApiResponse,
  type ResponseAction,
  type ResponseActionContext
} from "./response-actions";

class ActionPage extends Page {
  readonly custom: string[] = [];

  override async handleResponseAction(
    action: ResponseAction,
    _context: ResponseActionContext
  ): Promise<boolean> {
    if (action.action !== "custom") return false;
    this.custom.push(String(action.data));
    return true;
  }
}

function response(actions: ResponseAction[]): DefaultApiResponse {
  return { error_code: 0, message: "", data: {}, actions };
}

describe("ResponseActionRunner", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("runs actions in order and delegates private actions to the page", async () => {
    document.body.innerHTML = `<main id="page"><button id="source"></button></main>`;
    const page = new ActionPage(document.querySelector<HTMLElement>("#page")!);
    const calls: string[] = [];
    page.feedback = {
      alert: vi.fn(async () => calls.push("alert")),
      close: vi.fn(),
      toast: vi.fn(async () => calls.push("toast"))
    };

    await page.responseActions.run(
      response([
        { action: ApiResponseAction.FEEDBACK, title: "Saved", mode: "toast" },
        { action: "custom", data: "private" },
        { action: ApiResponseAction.FEEDBACK, title: "Done", mode: "alert" }
      ]),
      document.querySelector<HTMLElement>("#source")!
    );

    expect(calls).toEqual(["toast", "alert"]);
    expect(page.custom).toEqual(["private"]);
    expect(page.feedback.toast).toHaveBeenCalledWith({ titleText: "Saved" });
    expect(page.feedback.alert).toHaveBeenCalledWith({ titleText: "Done" });
  });

  it("resolves explicit and Form feedback targets, starts toast immediately, and awaits alert", async () => {
    document.body.innerHTML = `
      <main id="page">
        <div id="explicit" data-om-component="feedback"></div>
        <div id="form-feedback" data-om-component="feedback"></div>
        <form id="source" data-om-feedback-target="#form-feedback"></form>
        <button id="button"></button>
      </main>
    `;
    const page = new ActionPage(document.querySelector<HTMLElement>("#page")!);
    const toast = deferred<unknown>();
    const explicitFeedback = { alert: vi.fn(), close: vi.fn(), toast: vi.fn(() => toast.promise) };
    const formFeedback = { alert: vi.fn(), close: vi.fn(), toast: vi.fn().mockResolvedValue({}) };
    const pageAlert = deferred<unknown>();
    page.feedback = { alert: vi.fn(() => pageAlert.promise), close: vi.fn(), toast: vi.fn() };
    vi.spyOn(page.components, "get").mockImplementation((target: HTMLElement | string) => {
      const element = typeof target === "string" ? document.querySelector(target) : target;
      if (element?.id === "explicit") return explicitFeedback as never;
      if (element?.id === "form-feedback") return formFeedback as never;
      return null;
    });
    const logged = vi.spyOn(page.logger, "error").mockImplementation(() => {});

    await page.responseActions.run(
      response([{ action: ApiResponseAction.FEEDBACK, target: "#explicit", title: "Explicit" }]),
      document.querySelector<HTMLFormElement>("#source")!
    );
    expect(explicitFeedback.toast).toHaveBeenCalledWith({ titleText: "Explicit" });
    toast.reject(new Error("toast failed"));
    await Promise.resolve();
    expect(logged).toHaveBeenCalledWith("Oldman response toast failed", expect.any(Error));

    await page.responseActions.run(
      response([{ action: ApiResponseAction.FEEDBACK, title: "Form" }]),
      document.querySelector<HTMLFormElement>("#source")!
    );
    expect(formFeedback.toast).toHaveBeenCalledWith({ titleText: "Form" });

    let finished = false;
    const pending = page.responseActions.run(
      response([{ action: ApiResponseAction.FEEDBACK, mode: "alert", title: "Page" }]),
      document.querySelector<HTMLButtonElement>("#button")!
    ).then(() => { finished = true; });
    await Promise.resolve();
    expect(finished).toBe(false);
    pageAlert.resolve({});
    await pending;
    expect(page.feedback.alert).toHaveBeenCalledWith({ titleText: "Page" });

    const canceledAlert = deferred<unknown>();
    vi.mocked(page.feedback.alert).mockImplementation(() => canceledAlert.promise);
    const controller = new AbortController();
    const canceled = page.responseActions.run(
      response([{ action: ApiResponseAction.FEEDBACK, mode: "alert", title: "Cancel" }]),
      document.querySelector<HTMLButtonElement>("#button")!,
      controller.signal
    );
    controller.abort();
    await expect(canceled).rejects.toMatchObject({ name: "AbortError" });
    expect(page.feedback.close).toHaveBeenCalledOnce();
  });

  it("stops when an unknown action is not handled", async () => {
    document.body.innerHTML = `<main id="page"><button id="source"></button></main>`;
    const page = new ActionPage(document.querySelector<HTMLElement>("#page")!);

    await expect(
      page.responseActions.run(
        response([{ action: "unknown" }, { action: "custom", data: "late" }]),
        document.querySelector<HTMLElement>("#source")!
      )
    ).rejects.toThrow("Unknown response action: unknown");
    expect(page.custom).toEqual([]);
  });

  it("replaces page-scoped html and preserves a source form root", async () => {
    document.body.innerHTML = `
      <main id="page">
        <form id="source" data-om-target="#panel" data-om-swap="outer"></form>
        <section id="panel"><div data-om-component="old"></div></section>
      </main>
      <section id="outside"></section>
    `;
    const page = new ActionPage(document.querySelector<HTMLElement>("#page")!);
    vi.spyOn(page.components, "unmount").mockResolvedValue();
    vi.spyOn(page.components, "unmountDescendants").mockResolvedValue();
    vi.spyOn(page.components, "mount").mockResolvedValue([]);

    await page.responseActions.run(
      response([{ action: ApiResponseAction.REPLACE_HTML, target: "#panel", swap: "inner", html: `<span>inner</span>` }]),
      document.querySelector<HTMLFormElement>("#source")!
    );
    expect(page.root.querySelector("#panel")?.innerHTML).toBe("<span>inner</span>");
    expect(page.components.unmountDescendants).toHaveBeenCalledWith(page.root.querySelector("#panel"));

    await page.responseActions.run(
      response([{ action: ApiResponseAction.REPLACE_HTML, html: `<article id="panel">new</article>` }]),
      document.querySelector<HTMLFormElement>("#source")!
    );

    expect(page.root.querySelector("#panel")?.tagName).toBe("ARTICLE");
    expect(page.components.unmount).toHaveBeenCalledOnce();

    document.body.innerHTML = `
      <main id="page">
        <form id="source" data-om-form action="/old"><input value="old"></form>
      </main>
    `;
    const nextPage = new ActionPage(document.querySelector<HTMLElement>("#page")!);
    vi.spyOn(nextPage.components, "unmountDescendants").mockResolvedValue();
    vi.spyOn(nextPage.components, "mount").mockResolvedValue([]);
    const form = document.querySelector<HTMLFormElement>("#source")!;

    await nextPage.responseActions.run(
      response([
        {
          action: ApiResponseAction.REPLACE_HTML,
          html: `<form id="source" data-om-form action="/new" data-version="2"><input value="new"></form>`
        }
      ]),
      form
    );

    expect(form.isConnected).toBe(true);
    expect(form.action).toContain("/new");
    expect(form.dataset.version).toBe("2");
    expect(form.querySelector<HTMLInputElement>("input")?.value).toBe("new");
    expect(nextPage.components.unmountDescendants).toHaveBeenCalledWith(form);
  });

  it("falls back to the source and honors an outer Form replacement", async () => {
    document.body.innerHTML = `
      <main id="page">
        <button id="button">old</button>
        <form id="form" data-om-swap="outer"></form>
      </main>
    `;
    const page = new ActionPage(document.querySelector<HTMLElement>("#page")!);
    vi.spyOn(page.components, "unmount").mockResolvedValue();
    vi.spyOn(page.components, "mount").mockResolvedValue([]);

    const button = document.querySelector<HTMLButtonElement>("#button")!;
    await page.responseActions.run(
      response([{ action: ApiResponseAction.REPLACE_HTML, html: "<span id='button'>new</span>" }]),
      button
    );
    expect(button.isConnected).toBe(true);
    expect(button.innerHTML).toBe('<span id="button">new</span>');

    const form = document.querySelector<HTMLFormElement>("#form")!;
    await page.responseActions.run(
      response([{ action: ApiResponseAction.REPLACE_HTML, html: "<form id='form' data-version='2'></form>" }]),
      form
    );
    expect(form.isConnected).toBe(false);
    expect(page.root.querySelector<HTMLFormElement>("#form")?.dataset.version).toBe("2");
  });

  it("requires targets to stay inside the current page", async () => {
    document.body.innerHTML = `
      <main id="page"><button id="source"></button></main>
      <section id="outside"></section>
    `;
    const page = new ActionPage(document.querySelector<HTMLElement>("#page")!);

    await expect(
      page.responseActions.run(
        response([
          { action: ApiResponseAction.REPLACE_HTML, target: "#outside", html: "changed" }
        ]),
        document.querySelector<HTMLElement>("#source")!
      )
    ).rejects.toThrow("Response action target not found");
    expect(document.querySelector("#outside")?.textContent).toBe("");

    await expect(
      page.responseActions.run(
        response([{ action: ApiResponseAction.REPLACE_HTML, target: "#page", html: "changed" }]),
        document.querySelector<HTMLElement>("#source")!
      )
    ).rejects.toThrow("Response action target not found");
    expect(page.root.textContent).not.toBe("changed");

    await expect(
      page.responseActions.run(response([]), page.root)
    ).rejects.toThrow("Response action source must be inside the current page");
  });

  it("awaits table reload and closes the source modal", async () => {
    document.body.innerHTML = `
      <main id="page">
        <section id="modal" data-om-component="modal"><button id="source"></button></section>
        <section id="table" data-om-component="table"></section>
      </main>
    `;
    const page = new ActionPage(document.querySelector<HTMLElement>("#page")!);
    const close = vi.fn();
    const reload = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(page.components, "get").mockImplementation((target: HTMLElement | string) => {
      const element = typeof target === "string" ? document.querySelector(target) : target;
      if (element?.id === "modal") return { close } as never;
      if (element?.id === "table") return { reload } as never;
      return null;
    });

    await page.responseActions.run(
      response([
        { action: ApiResponseAction.CLOSE_MODAL },
        { action: ApiResponseAction.RELOAD_TABLE, target: "#table" }
      ]),
      document.querySelector<HTMLElement>("#source")!
    );

    expect(close).toHaveBeenCalledOnce();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("aborts an awaited redirect delay", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `<main id="page"><button id="source"></button></main>`;
    const page = new ActionPage(document.querySelector<HTMLElement>("#page")!);
    const controller = new AbortController();
    const currentUrl = window.location.href;

    const pending = page.responseActions.run(
      response([{ action: ApiResponseAction.REDIRECT, url: "/next", delay_ms: 1000 }]),
      document.querySelector<HTMLElement>("#source")!,
      controller.signal
    );
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    await vi.runAllTimersAsync();
    expect(window.location.href).toBe(currentUrl);
    vi.useRealTimers();
  });
});

// Keep construction available to downstream packages without a second registry.
expect(ResponseActionRunner).toBeTypeOf("function");

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}
