import { describe, expect, it, vi } from "vitest";
import { BackToTop } from "./back-to-top";

describe("BackToTop", () => {
  it("按滚动阈值切换按钮语义可见状态", async () => {
    document.body.innerHTML = `<button hidden></button>`;
    const root = document.querySelector<HTMLElement>("button")!;
    const component = new BackToTop(root, { threshold: 80 });
    const visibilityChanged = vi.fn();
    root.addEventListener("om:back-to-top:visibility", visibilityChanged);

    await component.start();
    expect(root.hidden).toBe(true);

    document.documentElement.scrollTop = 120;
    window.dispatchEvent(new Event("scroll"));

    expect(root.hidden).toBe(false);
    expect(root.dataset.omState).toBe("visible");
    expect(root.getAttribute("aria-hidden")).toBe("false");
    expect(visibilityChanged).toHaveBeenLastCalledWith(
      expect.objectContaining({ detail: { component, visible: true } })
    );

    document.documentElement.scrollTop = 20;
    window.dispatchEvent(new Event("scroll"));

    expect(root.hidden).toBe(true);
    expect(root.dataset.omState).toBe("hidden");

    await component.stop();
  });

  it("点击按钮时回到页面顶部", async () => {
    document.body.innerHTML = `<button></button>`;
    const root = document.querySelector<HTMLElement>("button")!;
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    document.documentElement.scrollTop = 150;
    document.body.scrollTop = 150;
    const component = new BackToTop(root);

    await component.start();
    root.click();

    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "auto" });
    expect(document.documentElement.scrollTop).toBe(0);
    expect(document.body.scrollTop).toBe(0);

    await component.stop();
    vi.unstubAllGlobals();
  });
});
