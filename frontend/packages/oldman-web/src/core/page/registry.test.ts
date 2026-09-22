import { describe, expect, it, vi } from "vitest";
import { Page } from "./page";
import { PageRegistry } from "./registry";

class NormalPage extends Page {
  static readonly pageName = "normal";
}

class HangingPage extends Page {
  static readonly pageName = "normal";
  override async unmount(): Promise<void> {
    // A host hook that never settles. Before the timeout this held pendingUnmount forever,
    // so Turbo's frame render never resumed and the next mount waited on it too.
    await new Promise<void>(() => {});
  }
}

function install(PageClass: typeof NormalPage, unmountTimeoutMs?: number) {
  document.body.innerHTML = `<main id="page" data-om-page="normal"></main>`;
  const registry = new PageRegistry(unmountTimeoutMs === undefined ? {} : { unmountTimeoutMs });
  registry.register("normal", PageClass);
  return registry;
}

describe("PageRegistry gives an unmount that never settles a deadline", () => {
  it("control - a hook that settles is awaited, not cut short", async () => {
    const registry = install(NormalPage, 50);
    await registry.mount(document);

    await registry.unmount();

    expect(registry.current).toBeNull();
  });

  it("resolves after the deadline and names the Page that stalled", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const registry = install(HangingPage, 20);
    await registry.mount(document);

    // Without the deadline this promise never settles and the test times out.
    await registry.unmount();

    expect(error).toHaveBeenCalled();
    expect(error.mock.calls.flat().join(" ")).toContain("normal");
    error.mockRestore();
  });

  it("a later mount is not blocked by the stalled unmount", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const registry = install(HangingPage, 20);
    await registry.mount(document);
    void registry.unmount();

    document.body.innerHTML = `<main id="next" data-om-page="normal"></main>`;
    registry.register("normal", NormalPage);
    const page = await registry.mount(document);

    expect(page).toBeInstanceOf(NormalPage);
    expect(page?.root.id).toBe("next");
    error.mockRestore();
  });
});
