import { afterEach, describe, expect, it, vi } from "vitest";
import type { HttpClient, HttpClientOptions } from "../http/client";
import { Page } from "../page/page";
import { createOldmanContext, resetOldmanContext, setOldmanContext } from "../runtime/context";
import { Component } from "./component";
import { ComponentManager } from "./manager";
import { ComponentRegistry } from "./registry";

class LifecycleComponent extends Component {
  readonly calls: string[];

  constructor(root: HTMLElement, calls: string[]) {
    super(root);
    this.calls = calls;
  }

  async beforeMount() {
    this.calls.push("beforeMount");
  }

  async mount() {
    this.calls.push("mount");
    this.cleanup(async () => {
      await Promise.resolve();
      this.calls.push("cleanup:second");
    });
    this.cleanup(() => {
      this.calls.push("cleanup:first");
    });
  }

  async afterMount() {
    this.calls.push("afterMount");
  }

  async beforeUnmount() {
    this.calls.push("beforeUnmount");
  }

  async unmount() {
    this.calls.push("unmount");
  }
}

describe("Component", () => {
  afterEach(() => {
    resetOldmanContext();
    vi.restoreAllMocks();
  });

  it("runs lifecycle hooks, cleanup in reverse order, and ends unmounted", async () => {
    document.body.innerHTML = `<section data-om-component="lifecycle"></section>`;
    const root = document.querySelector<HTMLElement>("[data-om-component]")!;
    const calls: string[] = [];
    const component = new LifecycleComponent(root, calls);

    await component.start();
    await component.stop();

    expect(calls).toEqual([
      "beforeMount",
      "mount",
      "afterMount",
      "beforeUnmount",
      "unmount",
      "cleanup:first",
      "cleanup:second"
    ]);
    expect(component.state).toBe("unmounted");
    expect(root.dataset.omComponentState).toBe("unmounted");
  });

  it("exposes a scoped preloader for component root", async () => {
    class PreloaderProbe extends Component {}

    document.body.innerHTML = `<div id="component-root"></div>`;
    const root = document.querySelector<HTMLElement>("#component-root")!;
    const component = new PreloaderProbe(root);

    component.preloader.show("Loading component");

    expect(root.dataset.omPreloaderStatus).toBe("loading");
    expect(root.querySelector("[data-om-scoped-preloader]")?.textContent).toContain("Loading component");

    await component.stop();
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();
  });

  it("creates component-scoped http clients and aborts only the component signal on stop", async () => {
    let requestSignal: AbortSignal | undefined;
    const http = {} as HttpClient;
    const httpFactory = vi.fn((options: HttpClientOptions = {}) => {
      requestSignal = options.signal;
      return http;
    });
    setOldmanContext(createOldmanContext({ httpFactory }));

    class HostPage extends Page {}
    class HttpComponent extends Component {}

    document.body.innerHTML = `<main id="page"><section id="component"></section></main>`;
    const page = new HostPage(document.querySelector<HTMLElement>("#page")!);
    const component = new HttpComponent(document.querySelector<HTMLElement>("#component")!, { page });

    expect(requestSignal).toBe(component.signal);
    expect(requestSignal).not.toBe(page.signal);
    expect(requestSignal?.aborted).toBe(false);
    expect(page.signal.aborted).toBe(false);

    await component.stop();

    expect(requestSignal?.aborted).toBe(true);
    expect(page.signal.aborted).toBe(false);
    await page.runCleanup();
  });
});

describe("ComponentManager", () => {
  it("mounts nested components and unmounts children before parents", async () => {
    const calls: string[] = [];

    class ParentComponent extends Component {
      static componentName = "parent";

      async mount() {
        calls.push("mount:parent");
      }

      async unmount() {
        calls.push("unmount:parent");
      }
    }

    class ChildComponent extends Component {
      static componentName = "child";

      async mount() {
        calls.push("mount:child");
      }

      async unmount() {
        calls.push("unmount:child");
      }
    }

    document.body.innerHTML = `
      <section data-om-component="parent">
        <div data-om-component="child"></div>
      </section>
    `;

    const registry = new ComponentRegistry();
    registry.register(ParentComponent);
    registry.register(ChildComponent);
    const manager = new ComponentManager({ registry });

    const mounted = await manager.mount(document);
    await manager.unmount(document);

    expect(mounted).toHaveLength(2);
    expect(calls).toEqual(["mount:parent", "mount:child", "unmount:child", "unmount:parent"]);
  });

  it("mounts child components created by parent render", async () => {
    const calls: string[] = [];

    class ParentComponent extends Component {
      static componentName = "parent";

      template() {
        return `<div data-om-component="child"></div>`;
      }

      async mount() {
        calls.push("mount:parent");
      }
    }

    class ChildComponent extends Component {
      static componentName = "child";

      async mount() {
        calls.push("mount:child");
      }
    }

    document.body.innerHTML = `<section data-om-component="parent"></section>`;

    const registry = new ComponentRegistry();
    registry.register(ParentComponent);
    registry.register(ChildComponent);
    const manager = new ComponentManager({ registry });

    const mounted = await manager.mount(document);

    expect(mounted).toHaveLength(2);
    expect(calls).toEqual(["mount:parent", "mount:child"]);
  });

  it("does not mount stale child roots replaced by parent render", async () => {
    const calls: string[] = [];

    class ParentComponent extends Component {
      static componentName = "parent";

      template() {
        return `<div data-om-component="child" data-role="fresh"></div>`;
      }
    }

    class ChildComponent extends Component {
      static componentName = "child";

      async mount() {
        calls.push(`mount:${this.root.dataset.role}`);
      }
    }

    document.body.innerHTML = `
      <section data-om-component="parent">
        <div data-om-component="child" data-role="stale"></div>
      </section>
    `;

    const registry = new ComponentRegistry();
    registry.register(ParentComponent);
    registry.register(ChildComponent);
    const manager = new ComponentManager({ registry });

    const mounted = await manager.mount(document);

    expect(mounted).toHaveLength(2);
    expect(calls).toEqual(["mount:fresh"]);
  });

  it("rolls back components mounted during the same mount call when a child fails", async () => {
    const calls: string[] = [];

    class ParentComponent extends Component {
      static componentName = "parent";

      async mount() {
        calls.push("mount:parent");
      }

      async unmount() {
        calls.push("unmount:parent");
      }
    }

    class ChildComponent extends Component {
      static componentName = "child";

      async mount() {
        calls.push("mount:child");
      }

      async unmount() {
        calls.push("unmount:child");
      }
    }

    class FailingComponent extends Component {
      static componentName = "failing";

      async mount() {
        calls.push("mount:failing");
        throw new Error("child failed");
      }

      async unmount() {
        calls.push("unmount:failing");
      }
    }

    document.body.innerHTML = `
      <section data-om-component="parent">
        <div data-om-component="child"></div>
        <div data-om-component="failing"></div>
      </section>
    `;

    const registry = new ComponentRegistry();
    registry.register(ParentComponent);
    registry.register(ChildComponent);
    registry.register(FailingComponent);
    const manager = new ComponentManager({ registry });

    await expect(manager.mount(document)).rejects.toThrow("child failed");

    expect(calls).toEqual(["mount:parent", "mount:child", "mount:failing", "unmount:child", "unmount:parent"]);
  });

  it("unmounts detached mounted descendants when unmounting a parent root", async () => {
    const calls: string[] = [];

    class ParentComponent extends Component {
      static componentName = "parent";

      async unmount() {
        calls.push("unmount:parent");
      }
    }

    class ChildComponent extends Component {
      static componentName = "child";

      async unmount() {
        calls.push("unmount:child");
      }
    }

    document.body.innerHTML = `
      <section data-om-component="parent">
        <div data-om-component="child"></div>
      </section>
    `;

    const parentRoot = document.querySelector<HTMLElement>('[data-om-component="parent"]')!;
    const childRoot = document.querySelector<HTMLElement>('[data-om-component="child"]')!;
    const registry = new ComponentRegistry();
    registry.register(ParentComponent);
    registry.register(ChildComponent);
    const manager = new ComponentManager({ registry });

    await manager.mount(document);
    childRoot.remove();
    await manager.unmount(parentRoot);

    expect(calls).toEqual(["unmount:child", "unmount:parent"]);
  });

  it("returns mounted component instances by root element or selector", async () => {
    class LookupComponent extends Component {
      static componentName = "lookup";
    }

    document.body.innerHTML = `<section id="lookup" data-om-component="lookup"></section>`;

    const root = document.querySelector<HTMLElement>("#lookup")!;
    const registry = new ComponentRegistry();
    registry.register(LookupComponent);
    const manager = new ComponentManager({ registry });

    const [component] = await manager.mount(document);

    expect(manager.get(root)).toBe(component);
    expect(manager.get("#lookup")).toBe(component);
    expect(manager.get("#missing")).toBeNull();
  });
});
