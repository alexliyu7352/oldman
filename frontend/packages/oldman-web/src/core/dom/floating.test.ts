import { describe, expect, it } from "vitest";
import { positionFloatingElement } from "./floating";

describe("positionFloatingElement", () => {
  it("flips and clamps a surface that would leave the viewport", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 320 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 240 });
    const reference = document.createElement("button");
    const floating = document.createElement("div");
    Object.defineProperty(reference, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ top: 210, right: 315, bottom: 230, left: 295, width: 20, height: 20 })
    });
    Object.defineProperty(floating, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ top: 0, right: 120, bottom: 80, left: 0, width: 120, height: 80 })
    });

    expect(positionFloatingElement(reference, floating, "bottom-end")).toBe("top-end");
    expect(floating.style.left).toBe("192px");
    expect(floating.style.top).toBe("122px");
    expect(floating.dataset.omEffectivePlacement).toBe("top-end");
  });

  it("aligns a right-start surface with the top edge of its reference", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });
    const reference = document.createElement("button");
    const floating = document.createElement("div");
    Object.defineProperty(reference, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ top: 100, right: 48, bottom: 132, left: 8, width: 40, height: 32 })
    });
    Object.defineProperty(floating, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ top: 0, right: 192, bottom: 120, left: 0, width: 192, height: 120 })
    });

    expect(positionFloatingElement(reference, floating, "right-start", { gap: 12 })).toBe("right-start");
    expect(floating.style.left).toBe("60px");
    expect(floating.style.top).toBe("100px");
  });
});
