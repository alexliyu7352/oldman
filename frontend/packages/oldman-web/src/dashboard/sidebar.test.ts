import { afterEach, describe, expect, it } from "vitest";
import { DashboardSidebar } from "./sidebar";

function sidebarMarkup(): string {
  return `
    <nav id="navbar-nav">
      <a href="/admin">Dashboard</a>
      <a href="/admin/projects">Projects</a>
      <a href="/admin/projects/archive">Project archive</a>
      <a href="/admin/project-settings">Project settings</a>
    </nav>
  `;
}

describe("DashboardSidebar", () => {
  afterEach(() => {
    document.body.replaceChildren();
    document.documentElement.setAttribute("data-layout", "vertical");
  });

  it("uses a neutral root route unless a consumer configures its dashboard path", async () => {
    const root = document.createElement("aside");
    root.innerHTML = `<nav id="navbar-nav"><a href="/">Home</a><a href="/dashboard">Dashboard</a></nav>`;
    document.body.append(root);
    const sidebar = new DashboardSidebar(root, { activePath: "/" });

    await sidebar.start();
    try {
      expect(sidebar.defaultDashboardPath).toBe("/");
      expect(root.querySelector<HTMLAnchorElement>('a[href="/"]')!.classList.contains("active")).toBe(true);
      expect(root.querySelector<HTMLAnchorElement>('a[href="/dashboard"]')!.classList.contains("active")).toBe(false);
    } finally {
      await sidebar.stop();
    }
  });

  it("cycles the collapsed rail through the hover states", async () => {
    const root = document.createElement("aside");
    root.innerHTML = `${sidebarMarkup()}<button id="vertical-hover" type="button">rail</button>`;
    document.body.append(root);
    const sidebar = new DashboardSidebar(root, { activePath: "/admin" });

    await sidebar.start();
    try {
      const toggle = root.querySelector<HTMLButtonElement>("#vertical-hover")!;
      const html = document.documentElement;

      toggle.click();
      expect(html.getAttribute("data-sidebar-size")).toBe("sm-hover");
      toggle.click();
      expect(html.getAttribute("data-sidebar-size")).toBe("sm-hover-active");
      toggle.click();
      expect(html.getAttribute("data-sidebar-size")).toBe("sm-hover");
    } finally {
      await sidebar.stop();
      document.documentElement.removeAttribute("data-sidebar-size");
    }
  });

  it("recomputes the active link after the main frame renders", async () => {
    const root = document.createElement("aside");
    root.innerHTML = sidebarMarkup();
    const frame = document.createElement("div");
    frame.id = "oldman-main";
    document.body.append(root, frame);
    // 不传 activePath：active 状态跟着当前地址走，Frame 渲染后要按新地址重算。
    window.history.pushState({}, "", "/admin");
    const sidebar = new DashboardSidebar(root, {});

    await sidebar.start();
    try {
      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin"]')!.classList.contains("active")).toBe(true);

      // Turbo 换了主 Frame 的内容，地址也变了：active 状态要跟着重算。
      window.history.pushState({}, "", "/admin/projects");
      frame.dispatchEvent(new CustomEvent("turbo:frame-render", { bubbles: true }));

      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin/projects"]')!.classList.contains("active")).toBe(true);
      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin"]')!.classList.contains("active")).toBe(false);
    } finally {
      await sidebar.stop();
      window.history.pushState({}, "", "/");
    }
  });

  it("uses the longest path-segment prefix for nested Admin routes", async () => {
    const root = document.createElement("aside");
    root.innerHTML = sidebarMarkup();
    document.body.append(root);
    const sidebar = new DashboardSidebar(root, { activePath: "/admin/projects/archive/42" });

    await sidebar.start();
    try {
      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin/projects/archive"]')!.classList.contains("active")).toBe(true);
      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin"]')!.classList.contains("active")).toBe(false);
      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin/projects"]')!.classList.contains("active")).toBe(false);
    } finally {
      await sidebar.stop();
    }
  });

  it("does not confuse neighboring route segments during prefix matching", async () => {
    const root = document.createElement("aside");
    root.innerHTML = sidebarMarkup();
    document.body.append(root);
    const sidebar = new DashboardSidebar(root, { activePath: "/admin/project-settings/42" });

    await sidebar.start();
    try {
      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin/project-settings"]')!.classList.contains("active")).toBe(true);
      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin/projects"]')!.classList.contains("active")).toBe(false);
    } finally {
      await sidebar.stop();
    }
  });

  it("normalizes a trailing slash before matching an active route", async () => {
    const root = document.createElement("aside");
    root.innerHTML = sidebarMarkup();
    document.body.append(root);
    const sidebar = new DashboardSidebar(root, { activePath: "/admin/projects/" });

    await sidebar.start();
    try {
      expect(root.querySelector<HTMLAnchorElement>('a[href="/admin/projects"]')!.classList.contains("active")).toBe(true);
    } finally {
      await sidebar.stop();
    }
  });

  it("scrolls the open group into view without cutting off its parent title", async () => {
    const scenarios = [
      { name: "group fits below the fold", groupTop: 400, linkBottom: 470, expectedScrollTop: 384 },
      { name: "group taller than the viewport", groupTop: 400, linkBottom: 900, expectedScrollTop: 616 },
      { name: "group already visible", groupTop: 50, linkBottom: 120, expectedScrollTop: 0 }
    ];
    for (const scenario of scenarios) {
      const root = document.createElement("aside");
      root.innerHTML = `
        <div class="oldman-sidebar-scroll">
          <ul id="navbar-nav">
            <li class="nav-item"><a href="/admin">Dashboard</a></li>
            <li class="nav-item" data-om-menu-item>
              <a data-om-menu-toggle href="#projects">Projects</a>
              <div data-om-menu-panel>
                <ul>
                  <li class="nav-item"><a href="/admin/projects">All projects</a></li>
                </ul>
              </div>
            </li>
          </ul>
        </div>
      `;
      document.body.append(root);
      const wrapper = root.querySelector<HTMLElement>(".oldman-sidebar-scroll")!;
      const group = root.querySelector<HTMLElement>("[data-om-menu-item]")!;
      const link = root.querySelector<HTMLElement>('a[href="/admin/projects"]')!;
      let scrollTop = 0;
      Object.defineProperty(wrapper, "clientHeight", { configurable: true, value: 300 });
      Object.defineProperty(wrapper, "scrollTop", {
        configurable: true,
        get: () => scrollTop,
        set: (value: number) => { scrollTop = value; }
      });
      const rect = (top: number, bottom: number) => ({ top, bottom, height: bottom - top }) as DOMRect;
      wrapper.getBoundingClientRect = () => rect(0, 300);
      group.getBoundingClientRect = () => rect(scenario.groupTop, scenario.linkBottom);
      link.getBoundingClientRect = () => rect(scenario.linkBottom - 40, scenario.linkBottom);
      const sidebar = new DashboardSidebar(root, { activePath: "/admin/projects" });

      await sidebar.start();
      try {
        expect(link.classList.contains("active"), scenario.name).toBe(true);
        expect(scrollTop, scenario.name).toBe(scenario.expectedScrollTop);
      } finally {
        await sidebar.stop();
        root.remove();
      }
    }
  });

  it("clears open panels selected through a custom menuPanelSelector", async () => {
    const root = document.createElement("aside");
    root.innerHTML = `
      <nav id="navbar-nav">
        <div data-custom-panel class="show">
          <a class="active" href="/records">Records</a>
        </div>
      </nav>
    `;
    document.body.append(root);
    const sidebar = new DashboardSidebar(root, {
      activePath: "/missing",
      menuPanelSelector: "[data-custom-panel]"
    });

    await sidebar.start();
    try {
      const panel = root.querySelector<HTMLElement>("[data-custom-panel]")!;
      expect(panel.classList.contains("show")).toBe(false);
      expect(panel.classList.contains("hidden")).toBe(true);
      expect(panel.hidden).toBe(true);
    } finally {
      await sidebar.stop();
    }
  });
});
