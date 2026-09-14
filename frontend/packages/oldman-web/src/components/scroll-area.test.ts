import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScrollArea } from "./scroll-area";

const simplebarState = vi.hoisted(() => ({
  instances: [] as Array<{
    element: HTMLElement;
    options: Record<string, unknown>;
    recalculate: ReturnType<typeof vi.fn>;
    scrollElement: HTMLElement;
    unMount: ReturnType<typeof vi.fn>;
  }>
}));

vi.mock("simplebar", () => ({
  default: class SimpleBarMock {
    static readonly instances = new WeakMap<Node, SimpleBarMock>();
    static readonly removeObserver = vi.fn();

    static getOptions(): Record<string, unknown> {
      return { autoHide: false };
    }

    static initDOMLoadedElements(): void {}

    readonly scrollElement: HTMLElement;
    readonly recalculate = vi.fn();
    readonly unMount = vi.fn();

    /**
     * 记录构造参数，便于断言 ScrollArea 是否正确透传配置。
     */
    constructor(readonly element: HTMLElement, readonly options: Record<string, unknown>) {
      this.scrollElement = document.createElement("div");
      this.scrollElement.className = "simplebar-content-wrapper";
      element.setAttribute("data-simplebar", "init");
      SimpleBarMock.instances.set(element, this);
      simplebarState.instances.push(this);
    }

    /**
     * 返回模拟的滚动容器。
     */
    getScrollElement(): HTMLElement {
      return this.scrollElement;
    }
  }
}));

describe("ScrollArea", () => {
  beforeEach(() => {
    simplebarState.instances = [];
    document.body.replaceChildren();
  });

  it("mounts SimpleBar and restores the original simplebar marker on unmount", async () => {
    document.body.innerHTML = `<section data-simplebar data-simplebar-auto-hide="false"></section>`;
    const root = document.querySelector<HTMLElement>("section")!;
    const scrollArea = new ScrollArea(root, { clickOnTrack: false });

    await scrollArea.start();

    expect(root.getAttribute("data-simplebar")).toBe("init");
    expect(simplebarState.instances).toHaveLength(1);
    expect(simplebarState.instances[0]?.options).toEqual({ autoHide: false, clickOnTrack: false });
    expect(scrollArea.getScrollElement()).toBe(simplebarState.instances[0]?.scrollElement);

    await scrollArea.stop();

    expect(simplebarState.instances[0]?.unMount).toHaveBeenCalledTimes(1);
    expect(root.getAttribute("data-simplebar")).toBe("");
  });

  it("removes compatibility marker when the root did not have data-simplebar before mount", async () => {
    document.body.innerHTML = `<section></section>`;
    const root = document.querySelector<HTMLElement>("section")!;
    const scrollArea = new ScrollArea(root);

    await scrollArea.start();
    await scrollArea.stop();

    expect(root.hasAttribute("data-simplebar")).toBe(false);
  });

  it("exposes recalculation and scroll helpers", async () => {
    document.body.innerHTML = `<section></section>`;
    const root = document.querySelector<HTMLElement>("section")!;
    const scrollArea = new ScrollArea(root);

    await scrollArea.start();
    const instance = simplebarState.instances.at(-1)!;
    const scrollTo = vi.fn();
    Object.assign(instance.scrollElement, { scrollTo });

    scrollArea.recalculate();
    scrollArea.scrollTo({ top: 120 });

    expect(instance.recalculate).toHaveBeenCalledTimes(1);
    expect(scrollTo).toHaveBeenCalledWith({ top: 120 });
  });
});
