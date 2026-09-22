import { describe, expect, it } from "vitest";
import { Dropdown } from "./dropdown";

describe("Dropdown", () => {
  it("opens from toggle and closes from outside click", async () => {
    document.body.innerHTML = `
      <div>
        <button data-om-dropdown-toggle aria-expanded="false">打开菜单</button>
        <div data-om-dropdown-menu class="hidden"></div>
      </div>
    `;
    const root = document.querySelector<HTMLElement>("div")!;
    const dropdown = new Dropdown(root);

    await dropdown.start();
    try {
      root.querySelector<HTMLButtonElement>("[data-om-dropdown-toggle]")!.click();

      expect(root.querySelector<HTMLElement>("[data-om-dropdown-menu]")!.classList.contains("hidden")).toBe(false);
      expect(root.querySelector<HTMLElement>("[data-om-dropdown-menu]")!.classList.contains("show")).toBe(true);
      expect(root.querySelector<HTMLButtonElement>("[data-om-dropdown-toggle]")!.getAttribute("aria-expanded")).toBe("true");

      document.body.click();

      expect(root.querySelector<HTMLElement>("[data-om-dropdown-menu]")!.classList.contains("hidden")).toBe(true);
      expect(root.querySelector<HTMLElement>("[data-om-dropdown-menu]")!.classList.contains("show")).toBe(false);
    } finally {
      await dropdown.stop();
    }
  });

  it("opens with the arrow keys and moves focus with arrows, Home and End", async () => {
    document.body.innerHTML = `
      <div>
        <button data-om-dropdown-toggle aria-expanded="false">Columns</button>
        <div data-om-dropdown-menu class="hidden" hidden>
          <label><input type="checkbox" id="first"> First</label>
          <button type="button" id="second">Second</button>
          <button type="button" id="hidden-item" hidden>Hidden</button>
          <a href="#" id="third">Third</a>
        </div>
      </div>
    `;
    const root = document.querySelector<HTMLElement>("div")!;
    const dropdown = new Dropdown(root);
    const press = (element: Element, key: string) => element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));

    await dropdown.start();
    try {
      const toggle = root.querySelector<HTMLButtonElement>("[data-om-dropdown-toggle]")!;
      toggle.focus();

      press(toggle, "ArrowDown");

      expect(root.querySelector<HTMLElement>("[data-om-dropdown-menu]")!.hidden).toBe(false);
      expect(document.activeElement?.id).toBe("first");

      press(document.activeElement!, "ArrowDown");
      expect(document.activeElement?.id).toBe("second");

      // The hidden item is skipped, and focus stops at the last item instead of wrapping.
      press(document.activeElement!, "ArrowDown");
      expect(document.activeElement?.id).toBe("third");
      press(document.activeElement!, "ArrowDown");
      expect(document.activeElement?.id).toBe("third");

      press(document.activeElement!, "Home");
      expect(document.activeElement?.id).toBe("first");
      press(document.activeElement!, "End");
      expect(document.activeElement?.id).toBe("third");
      press(document.activeElement!, "ArrowUp");
      expect(document.activeElement?.id).toBe("second");

      document.body.click();
      toggle.focus();
      press(toggle, "ArrowUp");
      expect(document.activeElement?.id).toBe("third");
    } finally {
      await dropdown.stop();
    }
  });

  it("supports Oldman dropdown menu class markers", async () => {
    document.body.innerHTML = `
      <div class="om-dropdown">
        <button type="button" data-om-dropdown-toggle aria-expanded="false">Open</button>
        <div class="om-dropdown-menu hidden" hidden>Menu</div>
      </div>
    `;
    const root = document.querySelector<HTMLElement>(".om-dropdown")!;
    const toggle = root.querySelector<HTMLButtonElement>("[data-om-dropdown-toggle]")!;
    const menu = root.querySelector<HTMLElement>(".om-dropdown-menu")!;
    const dropdown = new Dropdown(root);

    await dropdown.start();
    try {
      toggle.click();
      expect(menu.hidden).toBe(false);
      expect(menu.classList.contains("hidden")).toBe(false);
      expect(menu.classList.contains("show")).toBe(true);
      expect(root.classList.contains("show")).toBe(true);
    } finally {
      await dropdown.stop();
    }
    expect(menu.hidden).toBe(true);
    expect(menu.classList.contains("hidden")).toBe(true);
    expect(menu.classList.contains("show")).toBe(false);
    expect(root.classList.contains("show")).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(menu.style.position).toBe("");
  });

  it("does not force scrollbars on menus that fit inside the viewport", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
    document.body.innerHTML = `
      <div class="om-dropdown">
        <button type="button" data-om-dropdown-toggle aria-expanded="false">Open</button>
        <div class="om-dropdown-menu hidden" hidden>Menu</div>
      </div>
    `;
    const root = document.querySelector<HTMLElement>(".om-dropdown")!;
    const toggle = root.querySelector<HTMLElement>("[data-om-dropdown-toggle]")!;
    const menu = root.querySelector<HTMLElement>(".om-dropdown-menu")!;
    Object.defineProperty(toggle, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ top: 20, bottom: 60, left: 1200, right: 1240, width: 40, height: 40 })
    });
    Object.defineProperty(menu, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ top: 0, bottom: 260, left: 0, right: 360, width: 360, height: 260 })
    });
    const dropdown = new Dropdown(root);

    await dropdown.start();
    try {
      toggle.click();

      expect(menu.style.overflowY).toBe("");
      expect(menu.style.maxHeight).toBe("");
    } finally {
      await dropdown.stop();
    }
  });

  it("ignores unrelated document events when markup is incomplete", async () => {
    document.body.innerHTML = `<div></div>`;
    const root = document.querySelector<HTMLElement>("div")!;
    const dropdown = new Dropdown(root);

    await dropdown.start();
    try {
      expect(() => document.body.click()).not.toThrow();
      expect(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))).not.toThrow();
    } finally {
      await dropdown.stop();
    }
  });
});
