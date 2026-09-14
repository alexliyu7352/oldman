import Waves from "node-waves";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  FeedbackAlertOptions,
  FeedbackResult
} from "../components/feedback";
import {
  Component,
  createOldmanContext,
  resetOldmanContext,
  setOldmanContext,
  type HttpClient,
  type Logger
} from "../core/index";
import { DashboardFeedback } from "./feedback";
import { DashboardPage, type DashboardPageOptions } from "./index";
import { SidebarMenu } from "../components/sidebar-menu";

vi.mock("node-waves", () => ({
  default: {
    init: vi.fn()
  }
}));

class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  closeCalls = 0;

  constructor(url: string | URL) {
    super();
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  close(): void {
    this.closeCalls += 1;
  }

  emit(eventName: string, payload: unknown): void {
    this.dispatchEvent(new MessageEvent(eventName, { data: JSON.stringify(payload) }));
  }
}

class RecordingFeedback extends DashboardFeedback {
  readonly alerts: unknown[] = [];

  override alert(options: string | FeedbackAlertOptions): Promise<FeedbackResult> {
    this.alerts.push(options);
    return Promise.resolve({
      isConfirmed: true,
      isDenied: false,
      isDismissed: false
    });
  }
}

class EventDashboardPage extends DashboardPage {
  extensionClients = 0;
  navigations: string[] = [];
  recordedFeedback!: RecordingFeedback;

  protected override createFeedback(): DashboardFeedback {
    this.recordedFeedback = new RecordingFeedback(this.root, { page: this });
    return this.recordedFeedback;
  }

  protected override bindUserEventStream(client: import("../sse/index").EventStreamClient): Array<() => void> {
    this.extensionClients += 1;
    return [client.on("app.status", () => undefined)];
  }

  protected override navigate(url: string): void {
    this.navigations.push(url);
  }
}

function installContext(): { html: ReturnType<typeof vi.fn>; logger: Logger } {
  const html = vi.fn(async () => '<div data-om-user-notification-fragment data-om-unread-count="0"></div>');
  const logger: Logger = {
    debug: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warn: vi.fn()
  };
  const http = {
    html,
    postJson: vi.fn()
  } as unknown as HttpClient;
  setOldmanContext(createOldmanContext({ http, logger }));
  return { html, logger };
}

async function flush(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("DashboardPage", () => {
  afterEach(() => {
    document.body.replaceChildren();
    delete document.documentElement.dataset.omSidebarOpen;
    document.documentElement.setAttribute("data-layout", "vertical");
    document.documentElement.setAttribute("data-sidebar-size", "lg");
    document.head.querySelectorAll('meta[name="oldman-user-events-url"]').forEach((item) => item.remove());
    FakeEventSource.instances = [];
    resetOldmanContext();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    // Layout defaults belong to one browser document, not an individual Page instance.
    document.replaceChild(document.createElement("html"), document.documentElement);
    document.documentElement.append(document.createElement("head"), document.createElement("body"));
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("initializes Waves once for the same body", async () => {
    const first = new DashboardPage({ root: document.body });
    await first.mount();
    await first.beforeUnmount();
    await first.unmountComponents();
    await first.runCleanup();

    const second = new DashboardPage({ root: document.body });
    await second.mount();
    await second.beforeUnmount();
    await second.unmountComponents();
    await second.runCleanup();

    expect(Waves.init).toHaveBeenCalledTimes(1);
  });

  it("initializes Waves again after Turbo replaces the body", async () => {
    const initialBody = document.createElement("body");
    document.documentElement.replaceChild(initialBody, document.body);
    const first = new DashboardPage({ root: initialBody });
    await first.mount();
    await first.beforeUnmount();
    await first.unmountComponents();
    await first.runCleanup();

    const replacementBody = document.createElement("body");
    document.documentElement.replaceChild(replacementBody, document.body);
    const second = new DashboardPage({ root: replacementBody });
    await second.mount();
    await second.beforeUnmount();
    await second.unmountComponents();
    await second.runCleanup();

    expect(Waves.init).toHaveBeenCalledTimes(2);
  });

  it("applies layout before the preloader and lets SidebarMenu clear stale mobile state", async () => {
    let layoutAtPreloaderMount: string | null = null;
    class LayoutRecordingPreloader extends Component {
      override async mount(): Promise<void> {
        layoutAtPreloaderMount = document.documentElement.getAttribute("data-layout");
      }
    }

    document.documentElement.setAttribute("data-layout", "stale");
    document.documentElement.dataset.omSidebarOpen = "true";
    document.body.innerHTML = '<div id="preloader" data-om-component="preloader"></div><aside data-om-component="sidebar-menu"></aside>';
    const page = new DashboardPage({
      componentLoaders: {
        preloader: async () => LayoutRecordingPreloader,
        "sidebar-menu": async () => SidebarMenu
      },
      layoutAttributes: {
        "data-layout": "semibox"
      },
      root: document.documentElement
    });

    await page.mount();
    try {
      expect(layoutAtPreloaderMount).toBe("semibox");
      expect(document.documentElement.dataset.omSidebarOpen).toBeUndefined();
    } finally {
      await page.beforeUnmount();
      await page.unmountComponents();
      await page.runCleanup();
    }
  });

  it("clears the main-frame loader and alerts after a Turbo network failure", async () => {
    installContext();
    document.body.innerHTML = `
      <turbo-frame id="oldman-main" data-turbo-action="advance">
        <main>Current page</main>
      </turbo-frame>
    `;
    const page = new EventDashboardPage({ root: document.documentElement });

    await page.mount();
    try {
      const frame = document.querySelector<HTMLElement>("#oldman-main")!;
      frame.dispatchEvent(new Event("turbo:before-fetch-request", { bubbles: true }));
      expect(frame.querySelector("[data-om-scoped-preloader]")).not.toBeNull();

      const error = new TypeError("Failed to fetch");
      frame.dispatchEvent(new CustomEvent("turbo:fetch-request-error", {
        bubbles: true,
        detail: { error }
      }));

      expect(frame.dataset.omFrameState).toBe("failed");
      expect(frame.dataset.omPreloaderStatus).toBe("idle");
      expect(frame.querySelector("[data-om-scoped-preloader]")).toBeNull();
      expect(page.recordedFeedback.alerts).toEqual([{
        icon: "error",
        title: "Request failed"
      }]);
    } finally {
      await page.beforeUnmount();
      await page.unmountComponents();
      await page.runCleanup();
    }
  });

  it("handles only non-HTML HTTP errors from main-frame navigation", async () => {
    installContext();
    document.body.innerHTML = `<turbo-frame id="oldman-main"><form></form></turbo-frame><turbo-frame id="other"></turbo-frame>`;
    const page = new EventDashboardPage({ root: document.documentElement });
    await page.mount();
    const frame = document.querySelector<HTMLElement>("#oldman-main")!;
    const responseEvent = (failed: boolean, isHTML: boolean) => new CustomEvent("turbo:before-fetch-response", {
      bubbles: true,
      cancelable: true,
      detail: { fetchResponse: { failed, isHTML } }
    });
    try {
      frame.dispatchEvent(new Event("turbo:before-fetch-request", { bubbles: true }));
      for (const [target, failed, isHTML] of [
        [frame, true, true], // HTML 403 belongs to Turbo's normal renderer.
        [frame, false, false],
        [frame.querySelector("form")!, true, false],
        [document.querySelector("#other")!, true, false]
      ] as const) {
        const event = responseEvent(failed, isHTML);
        target.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(false);
        expect(frame.dataset.omFrameState).toBe("loading");
        expect(page.recordedFeedback.alerts).toEqual([]);
      }

      const error = responseEvent(true, false);
      frame.dispatchEvent(error);
      expect(error.defaultPrevented).toBe(true);
      expect(frame.dataset.omFrameState).toBe("failed");
      expect(frame.querySelector("[data-om-scoped-preloader]")).toBeNull();
      expect(page.signal.aborted).toBe(false);
      expect(page.recordedFeedback.alerts).toEqual([{ icon: "error", title: "Request failed" }]);
    } finally {
      await page.beforeUnmount();
      await page.unmountComponents();
      await page.runCleanup();
    }
    const afterCleanup = responseEvent(true, false);
    frame.dispatchEvent(afterCleanup);
    expect(afterCleanup.defaultPrevented).toBe(false);
    expect(page.recordedFeedback.alerts).toHaveLength(1);
  });

  it("honors the nested sidebar default size when the top-level shorthand is absent", async () => {
    const page = new DashboardPage({
      root: document.body,
      sidebarOptions: {
        defaultSidebarSize: "sm-hover"
      }
    });

    await page.mount();
    try {
      expect(document.documentElement.getAttribute("data-sidebar-size")).toBe("sm-hover");
    } finally {
      await page.beforeUnmount();
      await page.unmountComponents();
      await page.runCleanup();
    }
  });

  it("accepts DashboardBackToTop-specific options in the public page contract", () => {
    const options: DashboardPageOptions = {
      backToTopOptions: {
        buttonOptions: { threshold: 240 },
        buttonSelector: "#custom-back-to-top"
      }
    };

    expect(options.backToTopOptions).toMatchObject({ buttonSelector: "#custom-back-to-top" });
  });

  it("routes Dashboard activity response actions to the transient topbar", async () => {
    document.body.innerHTML = `
      <header id="page-topbar">
        <button id="source"></button>
        <section data-om-activity-notifications>
          <div data-om-activity-notification-list></div>
          <span data-om-activity-notification-count>0</span>
        </section>
      </header>
    `;
    const page = new DashboardPage({ root: document.documentElement });
    await page.mount();
    try {
      await page.responseActions.run(
        {
          error_code: 0,
          message: "",
          data: {},
          actions: [{
            action: "dashboard_activity",
            title: "Profile updated",
            description: "Alice was saved",
            tone: "success"
          }]
        },
        document.querySelector<HTMLElement>("#source")!
      );

      expect(document.querySelector("[data-om-activity-notification-item]")?.textContent).toContain("Profile updated");
      expect(document.querySelector("[data-om-activity-notification-count]")?.textContent).toBe("1");
    } finally {
      await page.beforeUnmount();
      await page.unmountComponents();
      await page.runCleanup();
    }
  });

  it("owns one user EventSource even when notification DOM is absent", async () => {
    installContext();
    document.head.insertAdjacentHTML("beforeend", '<meta name="oldman-user-events-url" content="/user-events">');
    const page = new EventDashboardPage({ root: document.documentElement });

    await page.mount();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0]?.url).toContain("/user-events");
    expect(page.extensionClients).toBe(1);

    document.dispatchEvent(new CustomEvent("om:i18n:change", {
      detail: { language: "zh-Hans", locale: "zh_Hans" }
    }));
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[0]?.closeCalls).toBe(1);
    expect(page.extensionClients).toBe(2);

    await page.beforeUnmount();
    await page.unmountComponents();
    await page.runCleanup();
    expect(FakeEventSource.instances[1]?.closeCalls).toBe(1);
  });

  it("closes the user EventSource on pagehide and restores it from the back-forward cache", async () => {
    installContext();
    document.head.insertAdjacentHTML("beforeend", '<meta name="oldman-user-events-url" content="/user-events">');
    const page = new EventDashboardPage({ root: document.documentElement });

    await page.mount();
    const initialSource = FakeEventSource.instances[0]!;

    window.dispatchEvent(new Event("pagehide"));
    expect(initialSource.closeCalls).toBe(1);

    const restored = new Event("pageshow");
    Object.defineProperty(restored, "persisted", { value: true });
    window.dispatchEvent(restored);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(page.extensionClients).toBe(2);

    window.dispatchEvent(new Event("pageshow"));
    expect(FakeEventSource.instances).toHaveLength(2);

    await page.beforeUnmount();
    await page.unmountComponents();
    await page.runCleanup();
    expect(FakeEventSource.instances[1]?.closeCalls).toBe(1);
  });

  it("shares the same EventSource with the notification adapter", async () => {
    const { html } = installContext();
    document.head.insertAdjacentHTML("beforeend", '<meta name="oldman-user-events-url" content="/user-events">');
    document.body.innerHTML = `
      <section data-om-user-notification-topbar data-om-topbar-url="/user-notifications/topbar" data-om-center-url="/user-notifications">
        <span data-om-user-notification-count hidden>0</span>
        <div data-om-user-notification-slot></div>
      </section>
    `;
    const page = new EventDashboardPage({ root: document.documentElement });

    await page.mount();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(page.extensionClients).toBe(1);
    expect(html).toHaveBeenCalledOnce();

    FakeEventSource.instances[0]?.dispatchEvent(new Event("open"));
    await flush();
    expect(html).toHaveBeenCalledTimes(2);

    await page.beforeUnmount();
    await page.unmountComponents();
    await page.runCleanup();
  });

  it("validates the unique user-events meta before opening a connection", async () => {
    installContext();
    const invalidValues = ["", "//outside", "/bad\\path", "/bad\npath", "https://outside.test/events"];
    for (const value of invalidValues) {
      document.head.querySelectorAll('meta[name="oldman-user-events-url"]').forEach((item) => item.remove());
      const meta = document.createElement("meta");
      meta.name = "oldman-user-events-url";
      meta.content = value;
      document.head.append(meta);
      const page = new EventDashboardPage({ root: document.documentElement });
      await expect(page.mount()).rejects.toThrow("oldman-user-events-url");
      await page.beforeUnmount();
      await page.unmountComponents();
      await page.runCleanup();
    }

    document.head.innerHTML = `
      <meta name="oldman-user-events-url" content="/events-one">
      <meta name="oldman-user-events-url" content="/events-two">
    `;
    const duplicate = new EventDashboardPage({ root: document.documentElement });
    await expect(duplicate.mount()).rejects.toThrow("exactly one");
    await duplicate.beforeUnmount();
    await duplicate.unmountComponents();
    await duplicate.runCleanup();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("stops reconnects before showing a valid Session-expired alert", async () => {
    const { html, logger } = installContext();
    document.head.insertAdjacentHTML("beforeend", '<meta name="oldman-user-events-url" content="/user-events">');
    document.body.innerHTML = `
      <section data-om-user-notification-topbar data-om-topbar-url="/user-notifications/topbar" data-om-center-url="/user-notifications">
        <span data-om-user-notification-count hidden>0</span>
        <div data-om-user-notification-slot></div>
      </section>
    `;
    const page = new EventDashboardPage({ root: document.documentElement });
    await page.mount();
    const source = FakeEventSource.instances[0]!;
    const notificationSignal = html.mock.calls[0]?.[1]?.signal as AbortSignal;
    expect(notificationSignal.aborted).toBe(false);

    source.emit("oldman.session.invalidated", {
      login_url: "/login",
      message: "Sign in again",
      title: "Session expired"
    });
    await flush();

    expect(source.closeCalls).toBe(1);
    expect(notificationSignal.aborted).toBe(true);
    expect(page.recordedFeedback.alerts[0]).toMatchObject({
      icon: "warning",
      text: "Sign in again",
      titleText: "Session expired"
    });
    expect(page.navigations).toEqual(["/login"]);

    const secondPage = new EventDashboardPage({ root: document.documentElement });
    await secondPage.mount();
    const secondSource = FakeEventSource.instances.at(-1)!;
    secondSource.emit("oldman.session.invalidated", {
      login_url: "//outside.test",
      message: "Bad",
      title: "Bad"
    });
    await flush();
    expect(secondPage.recordedFeedback.alerts).toHaveLength(0);
    expect(logger.error).toHaveBeenCalled();

    await page.beforeUnmount();
    await page.unmountComponents();
    await page.runCleanup();
    await secondPage.beforeUnmount();
    await secondPage.unmountComponents();
    await secondPage.runCleanup();
  });
});
