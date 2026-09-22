import { afterEach, describe, expect, it, vi } from "vitest";
import { SidebarMenu } from "./sidebar-menu";

function groupMarkup(): string {
  return `
    <ul id="navbar-nav">
      <li data-om-menu-item class="oldman-menu-item">
        <button data-om-menu-toggle aria-expanded="false"><i></i><span class="menu-text">目录</span></button>
        <ul data-om-menu-panel class="hidden" hidden>
          <li><a href="/catalog/channels" class="menu-link active" data-turbo-frame="oldman-main">频道</a></li>
          <li><a href="/catalog/feeds" class="menu-link">源</a></li>
        </ul>
      </li>
      <li data-om-menu-item class="oldman-menu-item">
        <button data-om-menu-toggle aria-expanded="false"><span class="menu-text">系统</span></button>
        <ul data-om-menu-panel class="hidden" hidden><li><a href="/users">用户</a></li></ul>
      </li>
    </ul>
  `;
}

const flyout = () => document.querySelector<HTMLElement>("[data-om-menu-flyout]");

function setViewportWidth(width: number): void {
  Object.defineProperty(document.documentElement, "clientWidth", {
    configurable: true,
    value: width
  });
}

describe("SidebarMenu", () => {
  afterEach(() => {
    document.body.replaceChildren();
    delete document.documentElement.dataset.omSidebarOpen;
    document.documentElement.setAttribute("data-sidebar-size", "lg");
    document.body.classList.remove("vertical-sidebar-enable");
  });

  it("toggles nested menu panels with aria state", async () => {
    const root = document.createElement("aside");
    root.innerHTML = `
      <li data-om-menu-item>
        <button data-om-menu-toggle aria-expanded="false">直播流</button>
        <ul data-om-menu-panel class="hidden"><li>活跃流</li></ul>
      </li>
    `;
    document.body.append(root);
    const sidebarMenu = new SidebarMenu(root);

    await sidebarMenu.start();
    try {
      root.querySelector<HTMLButtonElement>("[data-om-menu-toggle]")!.click();

      expect(root.querySelector<HTMLElement>("[data-om-menu-panel]")!.classList.contains("hidden")).toBe(false);
      expect(root.querySelector<HTMLElement>("[data-om-menu-panel]")!.classList.contains("show")).toBe(true);
      expect(root.querySelector<HTMLElement>("[data-om-menu-panel]")!.hidden).toBe(false);
      expect(root.querySelector<HTMLButtonElement>("[data-om-menu-toggle]")!.getAttribute("aria-expanded")).toBe("true");
      expect(root.querySelector<HTMLElement>("[data-om-menu-item]")!.classList.contains("open")).toBe(true);
    } finally {
      await sidebarMenu.stop();
    }
  });

  it("opens a group flyout beside the collapsed rail on hover, click and arrow keys", async () => {
    vi.useFakeTimers();
    document.documentElement.setAttribute("data-sidebar-size", "sm");
    const root = document.createElement("aside");
    root.innerHTML = groupMarkup();
    document.body.append(root);
    const sidebarMenu = new SidebarMenu(root);
    const [catalogToggle, systemToggle] = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-om-menu-toggle]"));

    await sidebarMenu.start();
    try {
      catalogToggle!.dispatchEvent(new Event("pointerover", { bubbles: true }));
      expect(flyout()).toBeNull();
      vi.advanceTimersByTime(200);

      const panel = flyout()!;
      expect(panel.querySelector(".oldman-menu-flyout-title")?.textContent).toBe("目录");
      expect(Array.from(panel.querySelectorAll<HTMLAnchorElement>(".oldman-menu-flyout-link"), (link) => link.getAttribute("href"))).toEqual(["/catalog/channels", "/catalog/feeds"]);
      expect(panel.querySelector(".oldman-menu-flyout-link.active")?.textContent).toBe("频道");
      expect(panel.querySelector(".oldman-menu-flyout-link")?.getAttribute("data-turbo-frame")).toBe("oldman-main");
      expect(catalogToggle!.getAttribute("aria-expanded")).toBe("true");
      // The inline panel stays collapsed: the rail has no room for it.
      expect(root.querySelector<HTMLElement>("[data-om-menu-panel]")!.hidden).toBe(true);
      // The common gesture: hover shows the flyout, then the user clicks the same icon. It must stay open.
      catalogToggle!.click();
      expect(flyout()).toBe(panel);

      // Leaving the icon closes after the grace period unless the pointer reaches the flyout.
      catalogToggle!.dispatchEvent(new MouseEvent("pointerout", { bubbles: true, relatedTarget: document.body }));
      vi.advanceTimersByTime(100);
      panel.dispatchEvent(new Event("pointerenter"));
      vi.advanceTimersByTime(200);
      expect(flyout()).toBe(panel);
      panel.dispatchEvent(new Event("pointerleave"));
      vi.advanceTimersByTime(150);
      expect(flyout()).toBeNull();
      expect(catalogToggle!.getAttribute("aria-expanded")).toBe("false");

      // Click opens the flyout instead of expanding inline and never toggles it closed; a second group replaces the first.
      catalogToggle!.click();
      expect(flyout()?.querySelector(".oldman-menu-flyout-title")?.textContent).toBe("目录");
      systemToggle!.click();
      expect(document.querySelectorAll("[data-om-menu-flyout]")).toHaveLength(1);
      expect(flyout()?.querySelector(".oldman-menu-flyout-title")?.textContent).toBe("系统");
      systemToggle!.click();
      expect(flyout()?.querySelector(".oldman-menu-flyout-title")?.textContent).toBe("系统");
      document.body.click();
      expect(flyout()).toBeNull();

      // Keyboard: ArrowRight opens and focuses the first link, arrows move, Escape returns to the icon.
      catalogToggle!.focus();
      catalogToggle!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true }));
      expect(document.activeElement?.getAttribute("href")).toBe("/catalog/channels");
      document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
      expect(document.activeElement?.getAttribute("href")).toBe("/catalog/feeds");
      document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
      expect(flyout()).toBeNull();
      expect(document.activeElement).toBe(catalogToggle);

      // Outside click closes; an expanded sidebar goes back to inline panels.
      catalogToggle!.click();
      document.body.click();
      expect(flyout()).toBeNull();
      document.documentElement.setAttribute("data-sidebar-size", "lg");
      catalogToggle!.click();
      expect(flyout()).toBeNull();
      expect(root.querySelector<HTMLElement>("[data-om-menu-panel]")!.hidden).toBe(false);
    } finally {
      await sidebarMenu.stop();
      vi.useRealTimers();
    }
    expect(flyout()).toBeNull();
  });

  it("opens and closes mobile sidebar from document controls", async () => {
    setViewportWidth(390);
    document.body.innerHTML = `
      <button data-om-sidebar-toggle>打开侧栏</button>
      <aside data-om-component="sidebar-menu"></aside>
      <div data-om-sidebar-backdrop class="hidden"></div>
    `;
    const root = document.querySelector<HTMLElement>("aside")!;
    const sidebarMenu = new SidebarMenu(root);

    await sidebarMenu.start();
    try {
      document.querySelector<HTMLButtonElement>("[data-om-sidebar-toggle]")!.click();

      expect(document.documentElement.dataset.omSidebarOpen).toBe("true");
      expect(document.body.classList.contains("vertical-sidebar-enable")).toBe(true);
      expect(document.querySelector<HTMLElement>("[data-om-sidebar-backdrop]")!.classList.contains("hidden")).toBe(false);

      document.querySelector<HTMLElement>("[data-om-sidebar-backdrop]")!.click();

      expect(document.documentElement.dataset.omSidebarOpen).toBeUndefined();
      expect(document.body.classList.contains("vertical-sidebar-enable")).toBe(false);
      expect(document.querySelector<HTMLElement>("[data-om-sidebar-backdrop]")!.classList.contains("hidden")).toBe(true);
    } finally {
      delete document.documentElement.dataset.omSidebarOpen;
      await sidebarMenu.stop();
    }
  });

  it("toggles mobile sidebar from the same document control", async () => {
    setViewportWidth(390);
    document.body.innerHTML = `
      <button data-om-sidebar-toggle>打开侧栏</button>
      <aside data-om-component="sidebar-menu"></aside>
      <div data-om-sidebar-backdrop class="hidden" hidden></div>
    `;
    const root = document.querySelector<HTMLElement>("aside")!;
    const sidebarMenu = new SidebarMenu(root);

    await sidebarMenu.start();
    try {
      const toggle = document.querySelector<HTMLButtonElement>("[data-om-sidebar-toggle]")!;

      toggle.click();
      expect(document.documentElement.dataset.omSidebarOpen).toBe("true");
      expect(document.body.classList.contains("vertical-sidebar-enable")).toBe(true);

      toggle.click();
      expect(document.documentElement.dataset.omSidebarOpen).toBeUndefined();
      expect(document.body.classList.contains("vertical-sidebar-enable")).toBe(false);
      expect(document.querySelector<HTMLElement>("[data-om-sidebar-backdrop]")!.hidden).toBe(true);
    } finally {
      delete document.documentElement.dataset.omSidebarOpen;
      document.body.classList.remove("vertical-sidebar-enable");
      await sidebarMenu.stop();
    }
  });

  it("keeps the open mobile sidebar unchanged when Escape is pressed", async () => {
    setViewportWidth(390);
    document.body.innerHTML = `
      <button data-om-sidebar-toggle>打开侧栏</button>
      <aside data-om-component="sidebar-menu"></aside>
      <div data-om-sidebar-backdrop class="hidden" hidden></div>
    `;
    const root = document.querySelector<HTMLElement>("aside")!;
    const sidebarMenu = new SidebarMenu(root);

    await sidebarMenu.start();
    try {
      document.querySelector<HTMLButtonElement>("[data-om-sidebar-toggle]")!.click();
      document.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Escape" }));

      expect(document.documentElement.dataset.omSidebarOpen).toBe("true");
      expect(document.body.classList.contains("vertical-sidebar-enable")).toBe(true);
      expect(document.querySelector<HTMLElement>("[data-om-sidebar-backdrop]")!.hidden).toBe(false);
    } finally {
      delete document.documentElement.dataset.omSidebarOpen;
      document.body.classList.remove("vertical-sidebar-enable");
      await sidebarMenu.stop();
    }
  });

  it("keeps root menus mutually exclusive when a new group opens", async () => {
    const root = document.createElement("aside");
    root.innerHTML = `
      <ul>
        <li data-om-menu-item class="active open">
          <button data-om-menu-toggle aria-expanded="true">Dashboard</button>
          <div data-om-menu-panel class="show">Overview</div>
        </li>
        <li data-om-menu-item>
          <button data-om-menu-toggle aria-expanded="false">Catalog</button>
          <div data-om-menu-panel class="hidden" hidden>Channels</div>
        </li>
      </ul>
    `;
    document.body.append(root);
    const sidebarMenu = new SidebarMenu(root);

    await sidebarMenu.start();
    try {
      const toggles = root.querySelectorAll<HTMLButtonElement>("[data-om-menu-toggle]");
      const firstPanel = root.querySelectorAll<HTMLElement>("[data-om-menu-panel]").item(0);
      const secondPanel = root.querySelectorAll<HTMLElement>("[data-om-menu-panel]").item(1);

      toggles.item(1).click();

      expect(firstPanel.classList.contains("show")).toBe(false);
      expect(firstPanel.hidden).toBe(true);
      expect(root.querySelectorAll<HTMLElement>("[data-om-menu-item]").item(0).classList.contains("active")).toBe(true);
      expect(root.querySelectorAll<HTMLElement>("[data-om-menu-item]").item(0).classList.contains("open")).toBe(false);
      expect(secondPanel.classList.contains("show")).toBe(true);
      expect(secondPanel.hidden).toBe(false);
      expect(root.querySelectorAll<HTMLElement>("[data-om-menu-item]").item(1).classList.contains("open")).toBe(true);
    } finally {
      await sidebarMenu.stop();
      root.remove();
    }
  });

  it("toggles desktop sidebar size from the document control", async () => {
    setViewportWidth(1440);
    document.documentElement.setAttribute("data-sidebar-size", "lg");
    document.body.innerHTML = `
      <button data-om-sidebar-toggle>
        <span class="hamburger-icon"></span>
      </button>
      <aside data-om-component="sidebar-menu"></aside>
      <div data-om-sidebar-backdrop class="hidden" hidden></div>
    `;
    const root = document.querySelector<HTMLElement>("aside")!;
    const sidebarMenu = new SidebarMenu(root);

    await sidebarMenu.start();
    try {
      const toggle = document.querySelector<HTMLButtonElement>("[data-om-sidebar-toggle]")!;

      toggle.click();
      expect(document.documentElement.getAttribute("data-sidebar-size")).toBe("sm");
      expect(document.body.classList.contains("vertical-sidebar-enable")).toBe(false);
      expect(document.querySelector(".hamburger-icon")?.classList.contains("open")).toBe(true);

      toggle.click();
      expect(document.documentElement.getAttribute("data-sidebar-size")).toBe("lg");
      expect(document.querySelector(".hamburger-icon")?.classList.contains("open")).toBe(false);
    } finally {
      document.documentElement.setAttribute("data-sidebar-size", "lg");
      await sidebarMenu.stop();
    }
  });
});
