import { afterEach, describe, expect, it, vi } from "vitest";
import { Tooltip } from "./tooltip";

describe("Tooltip", () => {
  afterEach(() => {
    vi.useRealTimers();
    document.body.replaceChildren();
  });

  it("shows from keyboard focus and closes with Escape", async () => {
    document.body.innerHTML = tooltipMarkup();
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

  it("waits 200ms on pointer hover and stays closed when the pointer leaves first", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = tooltipMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='tooltip']")!;
    const trigger = root.querySelector<HTMLButtonElement>("button")!;
    const content = root.querySelector<HTMLElement>("[data-om-tooltip-content]")!;
    const tooltip = new Tooltip(root);

    await tooltip.start();
    trigger.dispatchEvent(new Event("mouseenter"));
    expect(content.hidden).toBe(true);
    vi.advanceTimersByTime(199);
    expect(content.hidden).toBe(true);
    vi.advanceTimersByTime(1);
    expect(content.hidden).toBe(false);

    trigger.dispatchEvent(new Event("mouseleave"));
    expect(content.hidden).toBe(true);

    trigger.dispatchEvent(new Event("mouseenter"));
    trigger.dispatchEvent(new Event("mouseleave"));
    vi.advanceTimersByTime(500);
    expect(content.hidden).toBe(true);
    await tooltip.stop();
  });

  it("renders the bubble from <body> while open and puts it back on close", async () => {
    document.body.innerHTML = tooltipMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='tooltip']")!;
    const trigger = root.querySelector<HTMLButtonElement>("button")!;
    const content = root.querySelector<HTMLElement>("[data-om-tooltip-content]")!;
    const tooltip = new Tooltip(root);

    await tooltip.start();
    trigger.focus();
    expect(content.parentElement).toBe(document.body);
    expect(content.hidden).toBe(false);

    trigger.blur();
    expect(content.parentElement).toBe(root);
    expect(content.hidden).toBe(true);
    expect(root.querySelector("[data-om-tooltip-content]")).toBe(content);
    await tooltip.stop();
    expect(document.body.contains(content)).toBe(true);
  });

  it("honours a data-om-delay override", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = tooltipMarkup('data-om-delay="0"');
    const root = document.querySelector<HTMLElement>("[data-om-component='tooltip']")!;
    const trigger = root.querySelector<HTMLButtonElement>("button")!;
    const content = root.querySelector<HTMLElement>("[data-om-tooltip-content]")!;
    const tooltip = new Tooltip(root);

    await tooltip.start();
    trigger.dispatchEvent(new Event("mouseenter"));
    expect(content.hidden).toBe(false);
    await tooltip.stop();
  });
});

function tooltipMarkup(rootAttributes = ""): string {
  return `
    <span data-om-component="tooltip" ${rootAttributes}>
      <button data-om-tooltip-trigger>Help</button>
      <span class="om-tooltip-content" data-om-tooltip-content>Useful detail</span>
    </span>
  `;
}
