import { describe, expect, it } from "vitest";
import { Tabs } from "./tabs";

describe("Tabs", () => {
  it("selects tabs with click and keyboard while skipping disabled tabs", async () => {
    document.body.innerHTML = `
      <section data-om-component="tabs">
        <div role="tablist">
          <button data-om-tab role="tab" aria-controls="one" aria-selected="true">One</button>
          <button data-om-tab role="tab" aria-controls="two" disabled>Two</button>
          <button data-om-tab role="tab" aria-controls="three">Three</button>
        </div>
        <div id="one" role="tabpanel">First</div>
        <div id="two" role="tabpanel">Second</div>
        <div id="three" role="tabpanel">Third</div>
      </section>`;
    const root = document.querySelector<HTMLElement>("[data-om-component='tabs']")!;
    const component = new Tabs(root);
    const tabs = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-om-tab]"));
    const [first, , last] = tabs;
    if (!first || !last) throw new Error("Tabs fixture is incomplete");

    await component.start();
    try {
      first.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowRight" }));
      expect(last.getAttribute("aria-selected")).toBe("true");
      expect(document.querySelector<HTMLElement>("#one")!.hidden).toBe(true);
      expect(document.querySelector<HTMLElement>("#three")!.hidden).toBe(false);

      first.click();
      expect(first.tabIndex).toBe(0);
      expect(last.tabIndex).toBe(-1);

      first.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "End" }));
      expect(last.getAttribute("aria-selected")).toBe("true");
    } finally {
      await component.stop();
    }
  });
});
