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
