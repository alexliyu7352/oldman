import { describe, expect, it } from "vitest";
import { Dropdown } from "./dropdown";
import { Modal } from "./modal";
import { Popover } from "./popover";

describe.each([
  ["Dropdown", Dropdown, "data-om-dropdown-toggle", "data-om-dropdown-menu"],
  ["Popover", Popover, "data-om-popover-trigger", "data-om-popover-content"]
] as const)("%s keyboard ownership", (_name, Surface, toggleAttribute, contentAttribute) => {
  it("does not steal Modal Escape, but closes an inner surface before its Modal", async () => {
    document.body.innerHTML = `
      <div id="outside">
        <button ${toggleAttribute}>Outside menu</button>
        <div ${contentAttribute} hidden>Outside content</div>
      </div>
      <section id="modal" hidden>
        <article data-om-modal-content>
          <button id="modal-button">Modal action</button>
          <div id="inside">
            <button ${toggleAttribute}>Inside menu</button>
            <div ${contentAttribute} hidden>Inside content</div>
          </div>
        </article>
      </section>
    `;
    const outsideRoot = document.querySelector<HTMLElement>("#outside")!;
    const insideRoot = document.querySelector<HTMLElement>("#inside")!;
    const modalRoot = document.querySelector<HTMLElement>("#modal")!;
    const outside = new Surface(outsideRoot);
    const inside = new Surface(insideRoot);
    const modal = new Modal(modalRoot);
    await outside.start();
    await inside.start();
    await modal.start();
    try {
      outside.toggleOpen(true);
      modal.open();
      const modalButton = document.querySelector<HTMLButtonElement>("#modal-button")!;
      modalButton.focus();
      modalButton.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      expect(modalRoot.hidden).toBe(true);
      expect(outsideRoot.querySelector<HTMLElement>(`[${contentAttribute}]`)!.hidden).toBe(false);

      modal.open();
      inside.toggleOpen(true);
      const insideButton = insideRoot.querySelector<HTMLButtonElement>("button")!;
      insideButton.focus();
      insideButton.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      expect(insideRoot.querySelector<HTMLElement>(`[${contentAttribute}]`)!.hidden).toBe(true);
      expect(modalRoot.hidden).toBe(false);
      expect(document.activeElement).toBe(insideButton);

      inside.toggleOpen(true);
      // Model the focus left by Tab; jsdom does not implement native Tab traversal.
      modalButton.focus();
      modalButton.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      expect(insideRoot.querySelector<HTMLElement>(`[${contentAttribute}]`)!.hidden).toBe(true);
      expect(modalRoot.hidden).toBe(false);
      expect(document.activeElement).toBe(insideButton);
      insideButton.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      expect(modalRoot.hidden).toBe(true);
    } finally {
      await modal.stop();
      await inside.stop();
      await outside.stop();
    }
  });

  it("keeps the launching menu item visible so Modal can restore its focus", async () => {
    document.body.innerHTML = `
      <div id="outside">
        <button ${toggleAttribute}>Menu</button>
        <div ${contentAttribute} hidden>
          <button id="launch" data-om-modal-target="#modal">Open Modal</button>
        </div>
      </div>
      <section id="modal" hidden>
        <article data-om-modal-content><button id="dismiss">Modal action</button></article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("#outside")!;
    const modalRoot = document.querySelector<HTMLElement>("#modal")!;
    const surface = new Surface(root);
    const modal = new Modal(modalRoot);
    await surface.start();
    await modal.start();
    try {
      root.querySelector<HTMLButtonElement>(`[${toggleAttribute}]`)!.click();
      const launch = document.querySelector<HTMLButtonElement>("#launch")!;
      launch.focus();
      launch.click();
      const dismiss = document.querySelector<HTMLButtonElement>("#dismiss")!;
      expect(document.activeElement).toBe(dismiss);
      dismiss.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      expect(modalRoot.hidden).toBe(true);
      expect(root.querySelector<HTMLElement>(`[${contentAttribute}]`)!.hidden).toBe(false);
      expect(document.activeElement).toBe(launch);
    } finally {
      await modal.stop();
      await surface.stop();
    }
  });
});
