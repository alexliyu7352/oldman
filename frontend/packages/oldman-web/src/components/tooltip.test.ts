import { describe, expect, it } from "vitest";
import { Tooltip } from "./tooltip";

describe("Tooltip", () => {
  it("shows from keyboard focus and closes with Escape", async () => {
    document.body.innerHTML = `
      <span data-om-component="tooltip">
        <button data-om-tooltip-trigger>Help</button>
        <span class="om-tooltip-content" data-om-tooltip-content>Useful detail</span>
      </span>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='tooltip']")!;
    const trigger = root.querySelector<HTMLButtonElement>("button")!;
    const content = root.querySelector<HTMLElement>("[data-om-tooltip-content]")!;
    const tooltip = new Tooltip(root);

    await tooltip.start();
    trigger.focus();
    expect(content.hidden).toBe(false);
    expect(trigger.getAttribute("aria-describedby")).toBe(content.id);

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(content.hidden).toBe(true);
    await tooltip.stop();
  });
});
