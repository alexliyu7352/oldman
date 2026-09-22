import { describe, expect, it, vi } from "vitest";
import { Component } from "./component";
import { ComponentManager } from "./manager";
import { ComponentRegistry } from "./registry";

class Healthy extends Component {
  static readonly componentName = "healthy";
  static mounted: string[] = [];
  static unmounted: string[] = [];
  override async mount() {
    Healthy.mounted.push(this.root.id);
  }
  override async unmount() {
    Healthy.unmounted.push(this.root.id);
  }
}

/** Stands in for the eleven components that throw out of mount() when their own markup is wrong. */
class BadMarkup extends Component {
  static readonly componentName = "bad-markup";
  override async mount() {
    throw new Error("BadMarkup requires data-whatever");
  }
}

class Nested extends Component {
  static readonly componentName = "nested";
  static mounted = 0;
  override async mount() {
    Nested.mounted += 1;
  }
}

function build(html: string) {
  Healthy.mounted = [];
  Healthy.unmounted = [];
  Nested.mounted = 0;
  document.body.innerHTML = html;
  const registry = new ComponentRegistry();
  registry.register("healthy", Healthy);
  registry.register("bad-markup", BadMarkup);
  registry.register("nested", Nested);
  const logger = { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() };
  return {
    logger,
    root: document.getElementById("page") as HTMLElement,
    // No Page here, so the manager reports through the injected logger.
    manager: new ComponentManager({ logger, registry })
  };
}

describe("ComponentManager isolates one component's mount failure", () => {
  it("control - with no failure every sibling mounts", async () => {
    const { root, manager } = build(`
      <div id="page">
        <div id="a" data-om-component="healthy"></div>
        <div id="b" data-om-component="healthy"></div>
      </div>`);

    const mounted = await manager.mount(root);

    expect(Healthy.mounted).toEqual(["a", "b"]);
    expect(mounted).toHaveLength(2);
  });

  it("a component whose markup is wrong does not take its siblings down", async () => {
    const { logger, root, manager } = build(`
      <div id="page">
        <div id="a" data-om-component="healthy"></div>
        <div id="broken" data-om-component="bad-markup"></div>
        <div id="c" data-om-component="healthy"></div>
      </div>`);

    const mounted = await manager.mount(root);

    expect(Healthy.mounted).toEqual(["a", "c"]);
    // The sibling mounted before the failure must not be rolled back.
    expect(Healthy.unmounted).toEqual([]);
    expect(mounted.map((component) => component.root.id)).toEqual(["a", "c"]);
    expect(document.getElementById("broken")!.dataset.omComponentState).toBe("failed");
    expect(logger.error).toHaveBeenCalledTimes(1);
  });

  it("skips the subtree of the component that failed", async () => {
    const { root, manager } = build(`
      <div id="page">
        <div id="broken" data-om-component="bad-markup">
          <div id="child" data-om-component="nested"></div>
        </div>
        <div id="after" data-om-component="healthy"></div>
      </div>`);

    await manager.mount(root);

    expect(Nested.mounted).toBe(0);
    expect(Healthy.mounted).toEqual(["after"]);
  });

  it("still propagates cancellation, which is not a component defect", async () => {
    const { root, manager } = build(`
      <div id="page">
        <div id="a" data-om-component="cancels"></div>
        <div id="b" data-om-component="healthy"></div>
      </div>`);
    class Cancels extends Component {
      static readonly componentName = "cancels";
      override async mount() {
        throw new DOMException("The operation was aborted", "AbortError");
      }
    }
    const registry = new ComponentRegistry();
    registry.register("cancels", Cancels);
    registry.register("healthy", Healthy);
    const cancelling = new ComponentManager({ logger: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }, registry });

    await expect(cancelling.mount(root)).rejects.toThrow("The operation was aborted");
    // Swallowing this would let a superseded navigation keep mounting into a dying page.
    expect(Healthy.mounted).toEqual([]);
    void manager;
  });
});
