import { describe, expect, it, vi } from "vitest";
import { CleanupRegistry } from "./cleanup";
import { EventService } from "./events";

describe("EventService", () => {
  it("delegates events inside a root and cleans them up", async () => {
    document.body.innerHTML = `<div id="root"><button data-save>Save</button></div>`;
    const root = document.querySelector<HTMLElement>("#root")!;
    const cleanup = new CleanupRegistry();
    const events = new EventService(root, cleanup);
    const handler = vi.fn();

    events.on("click", "[data-save]", handler);
    root.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await cleanup.run();
    root.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0]![1]).toBe(root.querySelector("button"));
  });

  it("delegates typed custom events inside a root and cleans them up", async () => {
    document.body.innerHTML = `<div id="root"><section data-panel></section></div>`;
    const root = document.querySelector<HTMLElement>("#root")!;
    const panel = root.querySelector<HTMLElement>("[data-panel]")!;
    const cleanup = new CleanupRegistry();
    const events = new EventService(root, cleanup);
    const handler = vi.fn();

    events.onCustom<{ value: string }>("om:custom", "[data-panel]", (event, matchedElement) => {
      event.detail.value.toUpperCase();
      handler(event.detail, matchedElement);
    });
    panel.dispatchEvent(new CustomEvent("om:custom", { bubbles: true, detail: { value: "ready" } }));
    await cleanup.run();
    panel.dispatchEvent(new CustomEvent("om:custom", { bubbles: true, detail: { value: "late" } }));

    expect(handler).toHaveBeenCalledOnce();
    expect(handler).toHaveBeenCalledWith({ value: "ready" }, panel);
  });

  it("listens to direct targets and emits typed custom events", async () => {
    document.body.innerHTML = `<div id="root"></div>`;
    const root = document.querySelector<HTMLElement>("#root")!;
    const cleanup = new CleanupRegistry();
    const events = new EventService(root, cleanup);
    const handler = vi.fn();

    events.listen<CustomEvent<{ value: string }>>(root, "om:ready", (event) => {
      event.detail.value.toUpperCase();
      handler(event.detail);
    });

    expect(events.emit(root, "om:ready", { value: "mounted" })).toBe(true);
    await cleanup.run();
    events.emit(root, "om:ready", { value: "late" });

    expect(handler).toHaveBeenCalledOnce();
    expect(handler).toHaveBeenCalledWith({ value: "mounted" });
  });
});
