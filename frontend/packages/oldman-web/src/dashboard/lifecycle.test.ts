import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Component } from "../core/component/component";
import { BasePage } from "../app/index";
import { SidebarMenu } from "../components/sidebar-menu";
import { startPageLifecycle } from "../core/page/lifecycle";
import { PageRegistry } from "../core/page/registry";
import { createOldmanContext, resetOldmanContext, setOldmanContext } from "../core/runtime/context";
import { DashboardPage } from "./index";

/** Track real EventStreamClient disposal without opening a network connection. */
class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];
  closed = false;

  constructor(_url: string) {
    super();
    FakeEventSource.instances.push(this);
  }

  close(): void { this.closed = true; }
}

let registry: PageRegistry;
const logger = { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() };

/** Use the real shared SidebarMenu instead of mocking the state being tested. */
class SidebarDashboard extends DashboardPage {
  constructor(root: HTMLElement) {
    super({ root, componentLoaders: { "sidebar-menu": async () => SidebarMenu } });
  }
}

function installSidebar(): void {
  document.body.insertAdjacentHTML("afterbegin", `
    <button data-om-sidebar-toggle><span class="hamburger-icon"></span></button>
    <aside data-om-component="sidebar-menu"><ul id="navbar-nav"></ul></aside>
    <button data-om-sidebar-backdrop class="hidden" hidden>Close sidebar</button>
  `);
}

/** Follow Turbo's pause/resume boundary, then await the real new Page mount. */
async function navigateFrame(pageName = "dashboard-review", selector = "#oldman-main"): Promise<void> {
  const frame = document.querySelector<HTMLElement>(selector)!;
  const next = document.createElement("turbo-frame");
  next.dataset.omPage = pageName;
  next.textContent = "Next page";
  let resume!: () => void;
  const resumed = new Promise<void>((resolve) => { resume = resolve; });
  frame.dispatchEvent(new CustomEvent("turbo:before-frame-render", {
    bubbles: true, cancelable: true, detail: { newFrame: next, resume }
  }));
  await resumed;
  frame.replaceChildren(...next.childNodes);
  frame.dispatchEvent(new CustomEvent("turbo:frame-render", { bubbles: true }));
  await vi.waitFor(() => expect(frame.dataset.omFrameState).toBe("mounted"));
}

beforeEach(() => {
  // A new document root isolates document-lifetime state, not just body contents.
  document.replaceChild(document.createElement("html"), document.documentElement);
  document.documentElement.append(document.createElement("head"), document.createElement("body"));
  document.body.dataset.omPage = "dashboard-review";
  document.body.innerHTML = '<button class="light-dark-mode">Theme</button><turbo-frame id="oldman-main"></turbo-frame>';
  document.head.innerHTML = '<meta name="oldman-user-events-url" content="/user-events">';
  vi.stubGlobal("EventSource", FakeEventSource);
  registry = new PageRegistry();
  setOldmanContext(createOldmanContext({ pageRegistry: registry, logger }));
});

afterEach(async () => {
  try {
    await registry.unmount();
  } finally {
    resetOldmanContext();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    FakeEventSource.instances = [];
  }
});

it("stops ordinary components once and releases the shell when one component fails", async () => {
  let stops = 0;
  class BrokenComponent extends Component {
    override async unmount(): Promise<void> {
      stops += 1;
      throw new Error("plugin cleanup failed");
    }
  }
  class TestDashboard extends DashboardPage {
    constructor(root: HTMLElement) {
      super(root);
      this.components.register("broken", BrokenComponent);
    }
  }
  registry.register("dashboard-review", TestDashboard);
  document.querySelector("#oldman-main")!.innerHTML = '<div data-om-component="broken"></div>';
  const page = (await registry.mount())!;
  const unmountComponents = vi.spyOn(page.components, "unmount");

  await expect(registry.unmount()).rejects.toThrow("plugin cleanup failed");

  expect(unmountComponents).toHaveBeenCalledTimes(1);
  expect(stops).toBe(1);
  expect(page.signal.aborted).toBe(true);
  expect(FakeEventSource.instances[0]?.closed).toBe(true);
  const theme = document.documentElement.dataset.theme;
  document.querySelector<HTMLButtonElement>(".light-dark-mode")!.click();
  expect(document.documentElement.dataset.theme).toBe(theme);
});

it("continues shell cleanup after a shell component fails to stop", async () => {
  const stopped = vi.fn();
  class GoodComponent extends Component {
    override async unmount(): Promise<void> { stopped(); }
  }
  class BrokenComponent extends Component {
    override async unmount(): Promise<void> { throw new Error("shell cleanup failed"); }
  }
  class TestDashboard extends DashboardPage {
    protected override createSidebar(): Component { return new GoodComponent(this.root, { page: this }); }
    protected override createTopbar(): Component { return new BrokenComponent(this.root, { page: this }); }
  }
  registry.register("dashboard-review", TestDashboard);
  await registry.mount();
  await registry.unmount();

  expect(stopped).toHaveBeenCalledTimes(1);
  expect(FakeEventSource.instances[0]?.closed).toBe(true);
  expect(logger.error).toHaveBeenCalledWith("[oldman] cleanup callback failed", expect.any(Error));
});

it("cleans acquired shell resources while preserving the original mount failure", async () => {
  const cleaned = vi.fn();
  class BrokenComponent extends Component {
    override async mount(): Promise<void> {
      this.cleanup(cleaned);
      throw new Error("shell start failed");
    }
  }
  class TestDashboard extends DashboardPage {
    protected override createTopbar(): Component { return new BrokenComponent(this.root, { page: this }); }
  }
  registry.register("dashboard-review", TestDashboard);

  await expect(registry.mount()).rejects.toThrow("shell start failed");

  expect(cleaned).toHaveBeenCalledTimes(1);
  expect(registry.current).toBeNull();
  expect(FakeEventSource.instances).toHaveLength(0);
});

it("releases the shell even if a Page override throws without calling super", async () => {
  class TestDashboard extends DashboardPage {
    override async beforeUnmount(): Promise<void> { throw new Error("page hook failed"); }
  }
  registry.register("dashboard-review", TestDashboard);
  await registry.mount();

  await expect(registry.unmount()).rejects.toThrow("page hook failed");

  expect(FakeEventSource.instances[0]?.closed).toBe(true);
});

it.each(["dashboard-review", "next-dashboard"])("preserves desktop choices when navigating to %s", async (pageName) => {
  vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(1440);
  installSidebar();
  class NextDashboard extends SidebarDashboard {}
  registry.register("dashboard-review", SidebarDashboard);
  registry.register("next-dashboard", NextDashboard);
  const stop = await startPageLifecycle({ registry });
  const previous = registry.current!;
  try {
    document.querySelector<HTMLButtonElement>(".light-dark-mode")!.click();
    document.querySelector<HTMLButtonElement>("[data-om-sidebar-toggle]")!.click();
    await navigateFrame(pageName);

    expect(registry.current).not.toBe(previous);
    expect(previous.signal.aborted).toBe(true);
    expect(FakeEventSource.instances[0]?.closed).toBe(true);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.sidebarSize).toBe("sm");
    expect(document.querySelector(".hamburger-icon")?.classList.contains("open")).toBe(true);
  } finally {
    await stop();
  }
});

it("hides the mobile backdrop on navigation and allows the next Page to reopen it", async () => {
  vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(390);
  installSidebar();
  registry.register("dashboard-review", SidebarDashboard);
  const stop = await startPageLifecycle({ registry });
  const toggle = document.querySelector<HTMLButtonElement>("[data-om-sidebar-toggle]")!;
  const backdrop = document.querySelector<HTMLButtonElement>("[data-om-sidebar-backdrop]")!;
  try {
    toggle.click();
    expect(backdrop.hidden).toBe(false);
    await navigateFrame();
    expect(backdrop.isConnected).toBe(true);
    expect(backdrop.hidden).toBe(true);
    expect(document.documentElement.dataset.omSidebarOpen).toBeUndefined();
    expect(document.body.classList.contains("vertical-sidebar-enable")).toBe(false);
    toggle.click();
    expect(backdrop.hidden).toBe(false);
    backdrop.click();
    expect(backdrop.hidden).toBe(true);
  } finally {
    await stop();
  }
});

it("uses the configured main Frame and leaves nested Frame renders local", async () => {
  class CustomPage extends BasePage {
    constructor(root: HTMLElement) { super({ root, mainFrameSelector: "#custom-main" }); }
  }
  registry.register("dashboard-review", CustomPage);
  const frame = document.querySelector<HTMLElement>("#oldman-main")!;
  frame.id = "custom-main";
  const stop = await startPageLifecycle({ registry });
  const previous = registry.current!;
  try {
    const nested = document.createElement("turbo-frame");
    frame.append(nested);
    const event = new CustomEvent("turbo:before-frame-render", {
      bubbles: true, cancelable: true,
      detail: { newFrame: document.createElement("turbo-frame"), resume: vi.fn() }
    });
    nested.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(registry.current).toBe(previous);

    frame.dispatchEvent(new Event("turbo:before-fetch-request", { bubbles: true }));
    expect(frame.dataset.omFrameState).toBe("loading");
    await navigateFrame("dashboard-review", "#custom-main");
    expect(registry.current).not.toBe(previous);
    expect(previous.signal.aborted).toBe(true);
    expect(frame.dataset.omFrameState).toBe("mounted");
    expect(frame.querySelector("[data-om-scoped-preloader]")).toBeNull();
  } finally {
    await stop();
  }
});

it("uses the owning Page selector when refreshing the notification center", async () => {
  class CustomDashboard extends DashboardPage {
    constructor(root: HTMLElement) { super({ root, mainFrameSelector: "#custom-main" }); }
  }
  registry.register("dashboard-review", CustomDashboard);
  const frame = document.querySelector<HTMLElement>("#oldman-main")!;
  frame.id = "custom-main";
  frame.innerHTML = `
    <section data-om-user-notification-center data-om-current-url="/user-notifications">
      <button data-om-user-notification-refresh-center>Refresh</button>
    </section>
  `;
  await registry.mount();
  document.querySelector<HTMLButtonElement>("[data-om-user-notification-refresh-center]")!.click();
  expect(frame.getAttribute("src")).toBe("/user-notifications");
});
