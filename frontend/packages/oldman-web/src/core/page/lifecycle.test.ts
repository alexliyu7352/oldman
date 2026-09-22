import { afterEach, describe, expect, it, vi } from "vitest";
import { Page } from "./page";
import { PageRegistry } from "./registry";
import { startPageLifecycle } from "./lifecycle";
import { BasePage } from "../../app/index";
import { Component } from "../component/component";

const calls: string[] = [];

class LifecyclePage extends Page {
  static pageName = "lifecycle";

  async mount() {
    calls.push(`mount:${this.root.id}`);
  }

  async unmount() {
    calls.push(`unmount:${this.root.id}`);
  }
}

describe("startPageLifecycle", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("removes turbo listeners when stopped", async () => {
    calls.length = 0;
    document.body.innerHTML = `<main id="first" data-om-page="lifecycle"></main>`;
    const registry = new PageRegistry();
    registry.register(LifecyclePage);

    const stop = await startPageLifecycle({ registry });
    await stop();

    document.body.innerHTML = `<main id="second" data-om-page="lifecycle"></main>`;
    document.dispatchEvent(new CustomEvent("turbo:load"));
    await Promise.resolve();

    expect(calls).toEqual(["mount:first", "unmount:first"]);
  });

  it("removes turbo listeners when initial mount fails", async () => {
    document.body.innerHTML = `<main id="first" data-om-page="lifecycle"></main>`;
    const registry = new PageRegistry();
    const mount = vi.spyOn(registry, "mount").mockRejectedValueOnce(new Error("broken")).mockResolvedValue(null);
    const unmount = vi.spyOn(registry, "unmount");

    await expect(startPageLifecycle({ registry })).rejects.toThrow("broken");

    document.dispatchEvent(new CustomEvent("turbo:before-render"));
    document.dispatchEvent(new CustomEvent("turbo:load"));
    await Promise.resolve();

    expect(mount).toHaveBeenCalledOnce();
    expect(unmount).not.toHaveBeenCalled();
  });

  it("serializes unmount and mount work across turbo events", async () => {
    calls.length = 0;
    document.body.innerHTML = `<main id="first" data-om-page="lifecycle"></main>`;
    const registry = new PageRegistry();
    registry.register(LifecyclePage);

    const stop = await startPageLifecycle({ registry });
    document.dispatchEvent(new CustomEvent("turbo:before-render"));
    document.body.innerHTML = `<main id="second" data-om-page="lifecycle"></main>`;
    document.dispatchEvent(new CustomEvent("turbo:load"));

    await vi.waitFor(() => {
      expect(calls).toEqual(["mount:first", "unmount:first", "mount:second"]);
    });
    await stop();
  });

  it("removes scoped preloader DOM before Turbo caches a snapshot", async () => {
    calls.length = 0;
    document.body.innerHTML = `
      <main id="first" data-om-page="lifecycle" data-om-preloader-status="loading">
        <div data-om-scoped-preloader></div>
        <section data-om-preloader-status="loading">
          <div data-om-scoped-preloader></div>
        </section>
      </main>
    `;
    const registry = new PageRegistry();
    registry.register(LifecyclePage);

    const stop = await startPageLifecycle({ registry });
    document.dispatchEvent(new CustomEvent("turbo:before-cache"));

    expect(document.querySelector("[data-om-scoped-preloader]")).toBeNull();
    expect(document.querySelector<HTMLElement>("#first")?.dataset.omPreloaderStatus).toBe("idle");
    expect(document.querySelector<HTMLElement>("section")?.dataset.omPreloaderStatus).toBe("idle");

    await stop();
  });

  it("removes scoped preloader DOM after Turbo restores a snapshot", async () => {
    calls.length = 0;
    document.body.innerHTML = `
      <main id="first" data-om-page="lifecycle" data-om-preloader-status="loading">
        <div data-om-scoped-preloader></div>
      </main>
    `;
    const registry = new PageRegistry();
    registry.register(LifecyclePage);

    const stop = await startPageLifecycle({ registry });
    document.dispatchEvent(new CustomEvent("turbo:render"));

    expect(document.querySelector("[data-om-scoped-preloader]")).toBeNull();
    expect(document.querySelector<HTMLElement>("#first")?.dataset.omPreloaderStatus).toBe("idle");

    await stop();
  });

  it("does not unmount the page for the document render event emitted after turbo-frame advance", async () => {
    calls.length = 0;
    document.body.innerHTML = `
      <main id="first" data-om-page="lifecycle">
        <turbo-frame id="oldman-main" data-turbo-action="advance"></turbo-frame>
      </main>
    `;
    const registry = new PageRegistry();
    registry.register(LifecyclePage);

    const stop = await startPageLifecycle({ registry });
    document.querySelector("turbo-frame")?.dispatchEvent(new CustomEvent("turbo:frame-render", { bubbles: true }));
    document.documentElement.dispatchEvent(new CustomEvent("turbo:before-render", { bubbles: true }));

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(calls).toEqual(["mount:first"]);
    await stop();
  });

  it("remounts the page when history restoration interrupts a promoted frame visit", async () => {
    calls.length = 0;
    document.body.innerHTML = `
      <main id="first" data-om-page="lifecycle">
        <turbo-frame id="oldman-main" data-turbo-action="advance"></turbo-frame>
      </main>
    `;
    const registry = new PageRegistry();
    registry.register(LifecyclePage);

    const stop = await startPageLifecycle({ registry });
    try {
      document.querySelector("turbo-frame")?.dispatchEvent(new CustomEvent("turbo:frame-render", { bubbles: true }));
      document.dispatchEvent(new CustomEvent("turbo:visit", { detail: { action: "restore" } }));
      document.documentElement.dispatchEvent(new CustomEvent("turbo:before-render", { bubbles: true }));
      document.body.innerHTML = `<main id="second" data-om-page="lifecycle"></main>`;
      document.dispatchEvent(new CustomEvent("turbo:render"));
      document.dispatchEvent(new CustomEvent("turbo:load"));

      await vi.waitFor(() => {
        expect(calls).toEqual(["mount:first", "unmount:first", "mount:second"]);
      });
    } finally {
      await stop();
    }
  });

  it("does not suppress document unmount after a plain oldman-main frame render", async () => {
    calls.length = 0;
    document.body.innerHTML = `
      <main id="first" data-om-page="lifecycle">
        <turbo-frame id="oldman-main"></turbo-frame>
      </main>
    `;
    const registry = new PageRegistry();
    registry.register(LifecyclePage);

    const stop = await startPageLifecycle({ registry });
    document.querySelector("turbo-frame")?.dispatchEvent(new CustomEvent("turbo:frame-render", { bubbles: true }));
    document.documentElement.dispatchEvent(new CustomEvent("turbo:before-render", { bubbles: true }));

    await vi.waitFor(() => {
      expect(calls).toEqual(["mount:first", "unmount:first"]);
    });
    await stop();
  });

  it("still unmounts the page after an unrelated turbo frame render", async () => {
    calls.length = 0;
    document.body.innerHTML = `
      <main id="first" data-om-page="lifecycle">
        <turbo-frame id="secondary-frame"></turbo-frame>
      </main>
    `;
    const registry = new PageRegistry();
    registry.register(LifecyclePage);

    const stop = await startPageLifecycle({ registry });
    document.querySelector("turbo-frame")?.dispatchEvent(new CustomEvent("turbo:frame-render", { bubbles: true }));
    document.documentElement.dispatchEvent(new CustomEvent("turbo:before-render", { bubbles: true }));

    await vi.waitFor(() => {
      expect(calls).toEqual(["mount:first", "unmount:first"]);
    });
    await stop();
  });

  it("continues queued lifecycle work after a turbo task fails", async () => {
    document.body.innerHTML = `<main id="first" data-om-page="lifecycle"></main>`;
    const registry = new PageRegistry();
    const error = new Error("mount failed");
    const mount = vi
      .spyOn(registry, "mount")
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce(null);
    const report = vi.spyOn(console, "error").mockImplementation(() => {});

    const stop = await startPageLifecycle({ registry });
    document.dispatchEvent(new CustomEvent("turbo:load"));

    await vi.waitFor(() => {
      expect(report).toHaveBeenCalledWith("Oldman page lifecycle task failed", error);
    });

    document.dispatchEvent(new CustomEvent("turbo:load"));

    await vi.waitFor(() => {
      expect(mount).toHaveBeenCalledTimes(3);
    });

    await stop();
  });

  it("stops after a queued turbo task fails and still attempts final unmount", async () => {
    document.body.innerHTML = `<main id="first" data-om-page="lifecycle"></main>`;
    const registry = new PageRegistry();
    const error = new Error("unmount failed");
    vi.spyOn(registry, "mount").mockResolvedValue(null);
    const unmount = vi.spyOn(registry, "unmount").mockRejectedValueOnce(error).mockResolvedValueOnce();
    const report = vi.spyOn(console, "error").mockImplementation(() => {});

    const stop = await startPageLifecycle({ registry });
    document.dispatchEvent(new CustomEvent("turbo:before-render"));

    await vi.waitFor(() => {
      expect(report).toHaveBeenCalledWith("Oldman page lifecycle task failed", error);
    });

    await stop();

    expect(unmount).toHaveBeenCalledTimes(2);
  });
});

/** Reproduce Turbo's pause/resume contract and promoted document event sequence. */
async function renderMainFrame(pageName: string, html: string, promote = true): Promise<void> {
  const frame = document.querySelector<HTMLElement>("#oldman-main")!;
  const newFrame = document.createElement("turbo-frame");
  newFrame.dataset.omPage = pageName;
  newFrame.innerHTML = html;
  let resume!: () => void;
  const resumed = new Promise<void>((resolve) => { resume = resolve; });
  const event = new CustomEvent("turbo:before-frame-render", {
    bubbles: true,
    cancelable: true,
    detail: { newFrame, resume }
  });
  frame.dispatchEvent(event);
  if (event.defaultPrevented) await resumed;
  frame.replaceChildren(...newFrame.childNodes);
  frame.dispatchEvent(new CustomEvent("turbo:frame-render", { bubbles: true }));
  frame.dispatchEvent(new CustomEvent("turbo:frame-load", { bubbles: true }));
  if (promote) finishFrameNavigation();
}

/** A promoted Frame visit emits document events without replacing the body. */
function finishFrameNavigation(): void {
  document.dispatchEvent(new CustomEvent("turbo:before-cache"));
  document.documentElement.dispatchEvent(new CustomEvent("turbo:before-render", { bubbles: true }));
  document.dispatchEvent(new CustomEvent("turbo:render"));
  document.dispatchEvent(new CustomEvent("turbo:load"));
}

describe("business Page navigation", () => {
  class PrivateComponent extends Component {
    static readonly componentName = "private-probe";

    override async mount(): Promise<void> {
      this.root.dataset.privateMounted = "true";
      this.cleanup(() => { this.root.dataset.privateStopped = "true"; });
    }
  }

  class PlainPage extends BasePage {
    constructor(root: HTMLElement) { super({ root }); }
  }

  class PrivatePage extends BasePage {
    constructor(root: HTMLElement) {
      super({ root, componentLoaders: { "private-probe": async () => PrivateComponent } });
    }

    override async handleResponseAction(action: { action: string }): Promise<boolean> {
      if (action.action !== "private_probe") return false;
      this.root.querySelector("button")!.textContent = "private action handled";
      return true;
    }
  }

  function installPage(): PageRegistry {
    document.body.innerHTML = `<main data-om-page="plain">
      <aside id="unchanged-shell"></aside>
      <turbo-frame id="oldman-main" data-turbo-action="advance" data-om-page="plain">
        <button>original</button>
      </turbo-frame>
    </main>`;
    const registry = new PageRegistry();
    registry.register("plain", PlainPage);
    return registry;
  }

  it("loads the target Page's private component and action without global registration", async () => {
    const registry = installPage();
    const loadPage = vi.fn(async (name: string) => { registry.register(name, PrivatePage); });
    const stop = await startPageLifecycle({ registry, loadPage });
    const first = registry.current!;
    const shell = document.querySelector("aside");
    try {
      await renderMainFrame("private", '<button>action</button><div data-om-component="private-probe"></div>');
      await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
      const second = registry.current!;
      expect(second).toBeInstanceOf(PrivatePage);
      expect(second).not.toBe(first);
      expect(first.signal.aborted).toBe(true);
      expect(first.state).toBe("unmounted");
      expect(loadPage).toHaveBeenCalledOnce();
      expect(document.querySelector("[data-private-mounted='true']")).not.toBeNull();
      expect(document.querySelector("aside")).toBe(shell);
      expect(second.root.dataset.omPage).toBe("private");
      await second.responseActions.run({
        error_code: 0, message: "", data: {}, actions: [{ action: "private_probe" }]
      }, second.root.querySelector("button")!);
      expect(second.root.querySelector("button")?.textContent).toBe("private action handled");

      const oldComponent = second.root.querySelector<HTMLElement>("[data-private-mounted]")!;
      await renderMainFrame("plain", "<button>back</button>");
      await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
      expect(registry.current).toBeInstanceOf(PlainPage);
      expect(second.signal.aborted).toBe(true);
      expect(oldComponent.dataset.privateStopped).toBe("true");
      // The private component is still not globally registered. The new Page's manager now
      // isolates that instead of failing the whole mount, so the evidence is an empty result
      // plus the failed marker rather than a rejection.
      const report = vi.spyOn(console, "error").mockImplementation(() => {});
      await expect(registry.current!.components.mount(oldComponent)).resolves.toEqual([]);
      expect(oldComponent.dataset.omComponentState).toBe("failed");
      expect(report.mock.calls.flat().join(" ")).toContain("private-probe");
      report.mockRestore();
    } finally { await stop(); }
  });

  it("creates a new instance even when two business pages share a Page class", async () => {
    const registry = installPage();
    const stop = await startPageLifecycle({ registry });
    const first = registry.current!;
    const mount = vi.spyOn(registry, "mount");
    try {
      await renderMainFrame("plain", "<button>next</button>");
      await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
      expect(registry.current).not.toBe(first);
      expect(first.signal.aborted).toBe(true);
      expect(mount).toHaveBeenCalledOnce();
    } finally { await stop(); }
  });

  it("releases shell resources after a target Page mount fails and can navigate again", async () => {
    const registry = installPage();
    const closeSubscription = vi.fn();
    const report = vi.spyOn(console, "error").mockImplementation(() => {});
    class BrokenPage extends BasePage {
      constructor(root: HTMLElement) { super({ root }); }
      protected override async mountShellComponents(): Promise<void> {}
      protected override async unmountShellComponents(): Promise<void> { closeSubscription(); }
      protected override async afterContentMounted(): Promise<void> { throw new Error("broken content"); }
    }
    registry.register("broken", BrokenPage);
    const stop = await startPageLifecycle({ registry });
    try {
      await renderMainFrame("broken", "<button>broken</button>");
      await vi.waitFor(() => expect(document.querySelector("#oldman-main")?.getAttribute("data-om-frame-state")).toBe("failed"));
      expect(closeSubscription).toHaveBeenCalledOnce();
      expect(registry.current).toBeNull();
      expect(report).toHaveBeenCalledWith("Oldman page lifecycle task failed", expect.objectContaining({ message: "broken content" }));
      await renderMainFrame("plain", "<button>recovered</button>");
      await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
      expect(registry.current).toBeInstanceOf(PlainPage);
    } finally { await stop(); report.mockRestore(); }
  });

  it("waits for old Page cleanup before replacing its DOM", async () => {
    const registry = installPage();
    const stop = await startPageLifecycle({ registry });
    let finishCleanup!: () => void;
    const pendingCleanup = new Promise<void>((resolve) => { finishCleanup = resolve; });
    const first = registry.current!;
    const beforeUnmount = vi.spyOn(first, "beforeUnmount").mockImplementation(() => pendingCleanup);
    try {
      const navigation = renderMainFrame("plain", "<button>next</button>");
      await vi.waitFor(() => expect(beforeUnmount).toHaveBeenCalledOnce());
      expect(document.querySelector("button")?.textContent).toBe("original");
      finishCleanup();
      await navigation;
      await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
      expect(document.querySelector("button")?.textContent).toBe("next");
    } finally { finishCleanup(); await stop(); }
  });

  it("does not destroy the Page on a failed fetch or an unrelated local Frame render", async () => {
    const registry = installPage();
    const stop = await startPageLifecycle({ registry });
    const first = registry.current!;
    try {
      const frame = document.querySelector("turbo-frame")!;
      frame.dispatchEvent(new Event("turbo:before-fetch-request", { bubbles: true }));
      frame.dispatchEvent(new Event("turbo:fetch-request-error", { bubbles: true }));
      const localFrame = document.createElement("turbo-frame");
      localFrame.id = "local-form";
      frame.append(localFrame);
      localFrame.dispatchEvent(new Event("turbo:before-frame-render", { bubbles: true }));
      localFrame.dispatchEvent(new Event("turbo:frame-render", { bubbles: true }));
      await Promise.resolve();
      expect(registry.current).toBe(first);
      expect(first.signal.aborted).toBe(false);
      expect(frame.querySelector("[data-om-scoped-preloader]")).toBeNull();
    } finally { await stop(); }
  });

  it("keeps newly mounted chart loading after promoted document events", async () => {
    const registry = installPage();
    const stop = await startPageLifecycle({ registry });
    try {
      await renderMainFrame("plain", '<section data-om-loading-initial="true"><div id="chart"></div></section>', false);
      await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
      const chart = document.querySelector("#chart")!;
      finishFrameNavigation();
      expect(chart.parentElement?.querySelector("[data-om-scoped-preloader]")).not.toBeNull();
      chart.dispatchEvent(new Event("om:component:render-complete", { bubbles: true }));
      expect(chart.parentElement?.querySelector("[data-om-scoped-preloader]")).toBeNull();
    } finally { await stop(); }
  });

  it("does not mark a new Page mounted before its asynchronous component finishes", async () => {
    const registry = installPage();
    let finishMount!: () => void;
    const pendingMount = new Promise<void>((resolve) => { finishMount = resolve; });
    class SlowComponent extends Component {
      override async mount(): Promise<void> { await pendingMount; }
    }
    class SlowPage extends BasePage {
      constructor(root: HTMLElement) {
        super({ root, componentLoaders: { slow: async () => SlowComponent } });
      }
    }
    registry.register("slow", SlowPage);
    const stop = await startPageLifecycle({ registry });
    try {
      await renderMainFrame("slow", '<section data-om-loading-initial="true"><div data-om-component="slow"></div></section>');
      await vi.waitFor(() => expect(document.querySelector("[data-om-component=slow]")?.getAttribute("data-om-component-state")).toBe("mounting"));
      expect(registry.current?.state).toBe("mounting");
      expect(document.querySelector("#oldman-main")?.getAttribute("data-om-frame-state")).toBe("mounting");
      expect(document.querySelector("section [data-om-scoped-preloader]")).not.toBeNull();
      finishMount();
      await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
    } finally { finishMount(); await stop(); }
  });

  it("clears an outstanding navigation loader before a document snapshot", async () => {
    const registry = installPage();
    const stop = await startPageLifecycle({ registry });
    const frame = document.querySelector<HTMLElement>("#oldman-main")!;
    try {
      frame.dispatchEvent(new Event("turbo:before-fetch-request", { bubbles: true }));
      expect(frame.dataset.omPreloaderStatus).toBe("loading");
      document.dispatchEvent(new Event("turbo:before-cache"));
      expect(frame.dataset.omFrameState).toBe("mounted");
      expect(frame.dataset.omPreloaderStatus).toBe("idle");
      expect(frame.querySelector("[data-om-scoped-preloader]")).toBeNull();
    } finally { await stop(); }
  });
});
