import { describe, expect, it, vi } from "vitest";
import { TransitionService } from "./transitions";

describe("TransitionService", () => {
  it("swaps inner content", async () => {
    document.body.innerHTML = `<div id="target"><span>old</span></div>`;
    const target = document.querySelector<HTMLElement>("#target")!;
    const next = document.createElement("strong");
    next.textContent = "new";

    await new TransitionService().swap(target, next, { mode: "inner", transition: "none" });

    expect(target.innerHTML).toBe("<strong>new</strong>");
  });

  it("shows and hides hidden elements with transitions", async () => {
    document.body.innerHTML = `<section id="panel" hidden></section>`;
    const panel = document.querySelector<HTMLElement>("#panel")!;
    const transitions = new TransitionService();

    await transitions.show(panel, "none");
    expect(panel.hidden).toBe(false);

    await transitions.hide(panel, "none");
    expect(panel.hidden).toBe(true);
  });

  it("keeps transition classes until the matching animation ends", async () => {
    const element = document.createElement("div");
    element.style.animationDuration = "1s";
    document.body.append(element);

    const promise = new TransitionService().enter(element, "fade");

    expect(element.classList.contains("om-fade-enter")).toBe(true);
    element.dispatchEvent(new Event("animationend"));
    await promise;

    expect(element.classList.contains("om-fade-enter")).toBe(false);
  });

  it("supports scale transitions for floating UI", async () => {
    const element = document.createElement("div");
    element.style.animationDuration = "120ms";
    document.body.append(element);

    const promise = new TransitionService().leave(element, "scale");

    expect(element.classList.contains("om-scale-leave")).toBe(true);
    element.dispatchEvent(new Event("animationend"));
    await promise;

    expect(element.classList.contains("om-scale-leave")).toBe(false);
  });

  it("toggles element visibility from its current hidden state", async () => {
    document.body.innerHTML = `<section id="panel" hidden></section>`;
    const panel = document.querySelector<HTMLElement>("#panel")!;
    const transitions = new TransitionService();

    await transitions.toggle(panel, undefined, "none");
    expect(panel.hidden).toBe(false);

    await transitions.toggle(panel, undefined, "none");
    expect(panel.hidden).toBe(true);
  });

  it("adds classes for the duration of an async callback and always removes them", async () => {
    const element = document.createElement("div");
    const callback = vi.fn(async () => {
      expect(element.classList.contains("is-loading")).toBe(true);
      throw new Error("fail");
    });

    await expect(new TransitionService().withClasses(element, ["is-loading"], callback)).rejects.toThrow("fail");

    expect(callback).toHaveBeenCalled();
    expect(element.classList.contains("is-loading")).toBe(false);
  });
});
