import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  FeedbackAlertOptions,
  FeedbackConfirmOptions,
  FeedbackResult,
  FeedbackToastOptions
} from "../components/feedback";
import type { HttpClient, I18nRuntime, Logger } from "../core/index";
import type { EventStreamClient } from "../sse/index";
import { DashboardFeedback } from "./feedback";
import {
  DashboardNotifications,
  type DashboardNotificationServices
} from "./notifications";

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

class FakeEventStreamClient {
  readonly payloadHandlers = new Map<string, Set<(payload: unknown) => void>>();
  readonly openHandlers = new Set<() => void>();

  on(eventName: string, handler: (payload: unknown) => void): () => void {
    const handlers = this.payloadHandlers.get(eventName) ?? new Set();
    handlers.add(handler);
    this.payloadHandlers.set(eventName, handlers);
    return () => handlers.delete(handler);
  }

  onOpen(handler: () => void): () => void {
    this.openHandlers.add(handler);
    return () => this.openHandlers.delete(handler);
  }

  emit(eventName: string, payload: unknown): void {
    for (const handler of this.payloadHandlers.get(eventName) ?? []) handler(payload);
  }

  open(): void {
    for (const handler of this.openHandlers) handler();
  }
}

class RecordingFeedback extends DashboardFeedback {
  readonly alertCalls: unknown[] = [];
  readonly toastCalls: unknown[] = [];
  readonly confirmCalls: unknown[] = [];
  nextConfirmed = false;
  nextDeleteConfirmed = true;

  override alert(options: string | FeedbackAlertOptions): Promise<FeedbackResult> {
    this.alertCalls.push(options);
    return Promise.resolve({
      isConfirmed: this.nextConfirmed,
      isDenied: false,
      isDismissed: false
    });
  }

  override toast(options: FeedbackToastOptions): Promise<void> {
    this.toastCalls.push(options);
    return Promise.resolve();
  }

  override confirm(options: FeedbackConfirmOptions): Promise<boolean> {
    this.confirmCalls.push(options);
    return Promise.resolve(this.nextDeleteConfirmed);
  }
}

class TestNotifications extends DashboardNotifications {
  readonly navigations: string[] = [];

  protected override navigate(url: string): void {
    this.navigations.push(url);
  }
}

const activeNotifications = new Set<DashboardNotifications>();

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function validFragment(count: number, title = "Newest"): string {
  return `
    <div data-om-user-notification-fragment data-om-unread-count="${count}">
      <a href="/user-notifications/17/open" data-om-user-notification-preview data-om-user-notification-id="17">${title}</a>
    </div>
  `;
}

function validNotification(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    body: "Disk is full",
    format: "text",
    href: null,
    icon: "ri-error-warning-line",
    level: "error",
    presentation: "toast",
    title: "Server warning",
    version: 1,
    ...overrides
  };
}

function installDom(): void {
  document.body.innerHTML = `
    <section
      data-om-user-notification-topbar
      data-om-topbar-url="/user-notifications/topbar"
      data-om-center-url="/user-notifications"
    >
      <span data-om-user-notification-count hidden>0</span>
      <div data-om-user-notification-slot><span id="old-preview">Old</span></div>
    </section>
    <span data-om-user-notification-count hidden>0</span>
    <div id="oldman-main" src="/user-notifications?state=unread&page=2">
      <section
        data-om-user-notification-center
        data-om-read-url="/user-notifications/read"
        data-om-delete-url="/user-notifications/delete"
        data-om-center-url="/user-notifications"
        data-om-current-url="/user-notifications?state=unread&page=2"
      >
        <button data-om-user-notification-mark-all-read>All</button>
        <button data-om-user-notification-refresh-center hidden>Refresh</button>
        <article data-om-user-notification-center-item data-om-user-notification-id="7">
          <input type="checkbox" data-om-user-notification-select>
        </article>
        <article data-om-user-notification-center-item data-om-user-notification-id="9">
          <input type="checkbox" data-om-user-notification-select>
        </article>
        <span data-om-user-notification-selection-count>0</span>
        <button data-om-user-notification-mark-selected-read disabled>Read</button>
        <button data-om-user-notification-delete-selected disabled>Delete</button>
      </section>
    </div>
  `;
}

function makeHarness(options: { html?: ReturnType<typeof vi.fn>; postJson?: ReturnType<typeof vi.fn> } = {}) {
  const html = options.html ?? vi.fn(async () => validFragment(2));
  const postJson = options.postJson ?? vi.fn(async () => ({ error_code: 0, data: { changed: 1 } }));
  const logger: Logger = {
    debug: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warn: vi.fn()
  };
  const i18n = {
    t: (message: string) => message
  } as I18nRuntime;
  const services: DashboardNotificationServices = {
    mainFrameSelector: "#oldman-main",
    http: { html, postJson } as unknown as HttpClient,
    i18n,
    logger
  };
  const feedback = new RecordingFeedback(document.documentElement);
  const notifications = new TestNotifications(services, feedback, document.documentElement);
  activeNotifications.add(notifications);
  return { feedback, html, logger, notifications, postJson };
}

async function flush(): Promise<void> {
  for (let index = 0; index < 8; index += 1) await Promise.resolve();
}

describe("DashboardNotifications", () => {
  afterEach(() => {
    for (const notifications of activeNotifications) notifications.stop();
    activeNotifications.clear();
    document.body.replaceChildren();
    document.head.querySelectorAll('meta[name="oldman-user-events-url"]').forEach((item) => item.remove());
    vi.restoreAllMocks();
  });

  it("validates and applies only one topbar fragment root", async () => {
    installDom();
    const harness = makeHarness();

    await harness.notifications.mount();

    expect(harness.html).toHaveBeenCalledWith(
      "/user-notifications/topbar",
      expect.objectContaining({
        redirectOnAuth: false,
        signal: expect.any(AbortSignal)
      })
    );
    expect(document.querySelector("#old-preview")).toBeNull();
    expect(document.querySelector("[data-om-user-notification-preview]")?.textContent).toBe("Newest");
    for (const count of document.querySelectorAll<HTMLElement>("[data-om-user-notification-count]")) {
      expect(count.textContent).toBe("2");
      expect(count.hidden).toBe(false);
    }

    harness.html.mockResolvedValueOnce('<div data-om-user-notification-fragment data-om-unread-count="-1"></div>');
    await harness.notifications.refreshTopbar();
    expect(document.querySelector("[data-om-user-notification-preview]")?.textContent).toBe("Newest");
    expect(harness.logger.error).toHaveBeenCalledOnce();
  });

  it("coalesces concurrent refreshes and never applies the stale response", async () => {
    installDom();
    const first = deferred<string>();
    const second = deferred<string>();
    const html = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const harness = makeHarness({ html });

    const firstCall = harness.notifications.refreshTopbar();
    const secondCall = harness.notifications.refreshTopbar();
    expect(html).toHaveBeenCalledTimes(1);

    first.resolve(validFragment(1, "Stale"));
    await flush();
    expect(html).toHaveBeenCalledTimes(2);
    expect(document.body.textContent).not.toContain("Stale");

    second.resolve(validFragment(4, "Latest"));
    await Promise.all([firstCall, secondCall]);
    expect(document.body.textContent).toContain("Latest");
    expect(document.querySelector<HTMLElement>("[data-om-user-notification-count]")?.textContent).toBe("4");
  });

  it("rejects malformed SSE payloads before UI and HTTP side effects", async () => {
    installDom();
    const harness = makeHarness();
    const stream = new FakeEventStreamClient();
    harness.notifications.bindEventStream(stream as unknown as EventStreamClient);

    const invalidPayloads = [
      ["oldman.notifications.created", null],
      ["oldman.notifications.created", { notification_id: true, created_at: "now", notification: validNotification() }],
      ["oldman.notifications.created", { notification_id: 1, created_at: "2026-08-15", notification: validNotification() }],
      ["oldman.notifications.push", { notification: validNotification({ href: "//outside.test" }) }],
      ["oldman.notifications.push", { notification: validNotification({ format: "markdown" }) }],
      ["oldman.notifications.sync", { changed_count: -1 }]
    ] as const;
    for (const [eventName, payload] of invalidPayloads) stream.emit(eventName, payload);
    await flush();

    expect(harness.logger.error).toHaveBeenCalledTimes(invalidPayloads.length);
    expect(harness.feedback.alertCalls).toHaveLength(0);
    expect(harness.feedback.toastCalls).toHaveLength(0);
    expect(harness.html).not.toHaveBeenCalled();
    expect(harness.postJson).not.toHaveBeenCalled();
  });

  it("preserves text/html boundaries and opens lightweight notification toasts on click", async () => {
    installDom();
    const harness = makeHarness();
    const stream = new FakeEventStreamClient();
    harness.notifications.bindEventStream(stream as unknown as EventStreamClient);
    harness.feedback.nextConfirmed = true;

    stream.emit("oldman.notifications.created", {
      created_at: "2026-08-15T12:00:00Z",
      notification: validNotification({
        body: "<strong>trusted</strong>",
        format: "html",
        href: "/reports/7",
        presentation: "modal",
        title: "<b>Plain title</b>"
      }),
      notification_id: 7
    });
    await flush();

    expect(harness.feedback.alertCalls[0]).toMatchObject({
      confirmButtonText: "Open",
      html: "<strong>trusted</strong>",
      icon: "error",
      showCancelButton: true,
      titleText: "<b>Plain title</b>"
    });
    expect(harness.feedback.alertCalls[0]).not.toHaveProperty("title");
    expect(harness.notifications.navigations).toEqual(["/user-notifications/7/open"]);
    expect(harness.html).toHaveBeenCalledOnce();
    expect(document.querySelector<HTMLElement>("[data-om-user-notification-refresh-center]")?.hidden).toBe(false);

    harness.feedback.nextConfirmed = false;
    stream.emit("oldman.notifications.push", {
      notification: validNotification({
        body: "plain <body>",
        href: "/temporary/notice",
        level: "warning",
        presentation: "toast"
      })
    });
    await flush();
    expect(harness.feedback.toastCalls.at(-1)).toMatchObject({
      icon: "warning",
      text: "plain <body>",
      titleText: "Server warning"
    });
    expect(harness.feedback.toastCalls.at(-1)).not.toHaveProperty("html");
    expect(harness.notifications.navigations).toEqual(["/user-notifications/7/open"]);
    const toastOptions = harness.feedback.toastCalls.at(-1) as FeedbackToastOptions;
    toastOptions.onClick?.();
    expect(harness.notifications.navigations).toEqual([
      "/user-notifications/7/open",
      "/temporary/notice"
    ]);
    expect(harness.html).toHaveBeenCalledOnce();
  });

  it("refreshes persistent state for created, sync, and native open but not push", async () => {
    installDom();
    const harness = makeHarness();
    const stream = new FakeEventStreamClient();
    harness.notifications.bindEventStream(stream as unknown as EventStreamClient);

    stream.emit("oldman.notifications.push", { notification: validNotification({ presentation: "none" }) });
    await flush();
    expect(harness.html).not.toHaveBeenCalled();
    expect(harness.feedback.toastCalls).toHaveLength(0);

    stream.emit("oldman.notifications.sync", { changed_count: 2 });
    await flush();
    expect(harness.html).toHaveBeenCalledOnce();
    expect(document.querySelector<HTMLElement>("[data-om-user-notification-refresh-center]")?.hidden).toBe(false);

    stream.open();
    await flush();
    expect(harness.html).toHaveBeenCalledTimes(2);
  });

  it("scopes selection and mutations to the current notification center", async () => {
    installDom();
    document.body.insertAdjacentHTML(
      "beforeend",
      '<section data-om-activity-notifications><input type="checkbox" checked data-om-activity-notification-select data-om-user-notification-id="99"></section>'
    );
    const harness = makeHarness();
    await harness.notifications.mount();
    harness.html.mockClear();
    const frame = document.querySelector<HTMLElement>("#oldman-main")!;
    const reload = vi.fn();
    Object.assign(frame, { reload });
    await flush();
    reload.mockClear();
    const selected = document.querySelectorAll<HTMLInputElement>("[data-om-user-notification-select]");
    selected[0]!.checked = true;
    selected[1]!.checked = true;
    selected[0]!.dispatchEvent(new Event("change", { bubbles: true }));

    expect(document.querySelector("[data-om-user-notification-selection-count]")?.textContent).toBe("2");
    document.querySelector<HTMLElement>("[data-om-user-notification-mark-selected-read]")!
      .click();
    await flush();

    expect(harness.postJson).toHaveBeenCalledWith(
      "/user-notifications/read",
      { ids: [7, 9] },
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    expect(frame.getAttribute("src")).toBe("/user-notifications?state=unread&page=2");
    expect(reload).toHaveBeenCalledOnce();
    expect(harness.html).toHaveBeenCalledOnce();

    document.querySelector<HTMLElement>("[data-om-user-notification-mark-all-read]")!.click();
    await flush();
    expect(harness.postJson).toHaveBeenCalledWith(
      "/user-notifications/read",
      { all: true },
      expect.any(Object)
    );

    harness.feedback.nextDeleteConfirmed = true;
    document.querySelector<HTMLElement>("[data-om-user-notification-delete-selected]")!.click();
    await flush();
    expect(harness.feedback.confirmCalls).toHaveLength(1);
    expect(harness.postJson).toHaveBeenCalledWith(
      "/user-notifications/delete",
      { ids: [7, 9] },
      expect.any(Object)
    );
  });

  it("keeps DOM unchanged when a mutation response is invalid", async () => {
    installDom();
    const postJson = vi.fn(async () => ({ error_code: 0, data: { changed: true } }));
    const harness = makeHarness({ postJson });
    await harness.notifications.mount();
    harness.html.mockClear();
    const frame = document.querySelector<HTMLElement>("#oldman-main")!;
    const reload = vi.fn();
    Object.assign(frame, { reload });
    await flush();
    reload.mockClear();

    document.querySelector<HTMLElement>("[data-om-user-notification-mark-all-read]")!.click();
    await flush();

    expect(harness.logger.error).toHaveBeenCalledOnce();
    expect(harness.feedback.alertCalls).toHaveLength(1);
    expect(harness.html).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
    expect(document.querySelectorAll("[data-om-user-notification-center-item]")).toHaveLength(2);
  });

  it("ignores in-flight results and delegated events after stop", async () => {
    installDom();
    const response = deferred<string>();
    const html = vi.fn(() => response.promise);
    const harness = makeHarness({ html });
    const refresh = harness.notifications.refreshTopbar();

    harness.notifications.stop();
    response.resolve(validFragment(9, "Too late"));
    await refresh;
    document.querySelector<HTMLElement>("[data-om-user-notification-mark-all-read]")!.click();
    await flush();

    expect(document.body.textContent).not.toContain("Too late");
    expect(harness.postJson).not.toHaveBeenCalled();
  });
});
