import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardTopbar, type DashboardTopbarNotificationDetail } from "./topbar";
import { createPreferenceStore } from "../core/services/preferences";
import { DASHBOARD_THEME_PREFERENCE_KEY } from "./theme";

class TestDashboardTopbar extends DashboardTopbar {
  renderNotification(detail: DashboardTopbarNotificationDetail): string {
    return this.notificationTemplate(detail);
  }
}

describe("DashboardTopbar", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("derives the breadcrumb from the sidebar path and page title when the page provides none", async () => {
    document.body.innerHTML = `
      <header id="page-topbar">
        <span data-om-topbar-breadcrumb-separator hidden></span>
        <nav data-om-topbar-breadcrumb></nav>
      </header>
      <aside data-om-sidebar>
        <ul>
          <li data-om-menu-item class="active open">
            <button type="button" data-om-menu-toggle><span class="menu-text">Authentication</span></button>
            <ul><li><a class="active" href="/admin/oldman_user"><span class="menu-text">Users</span></a></li></ul>
          </li>
        </ul>
      </aside>
      <turbo-frame id="oldman-main"><h1 class="om-page-title">Edit User</h1></turbo-frame>
    `;
    const topbar = new DashboardTopbar(document.body);
    await topbar.start();

    try {
      const slot = document.querySelector<HTMLElement>("[data-om-topbar-breadcrumb]")!;
      const items = Array.from(slot.querySelectorAll("li")).map((item) => item.textContent?.trim());
      expect(items).toEqual(["Authentication", "Users", "Edit User"]);
      expect(slot.querySelector("a")?.getAttribute("href")).toBe("/admin/oldman_user");
      expect(slot.querySelector("[aria-current='page']")?.textContent).toBe("Edit User");
      expect(document.querySelector<HTMLElement>("[data-om-topbar-breadcrumb-separator]")!.hidden).toBe(false);

      // Same label as the active item collapses into one current entry.
      document.querySelector("#oldman-main")!.innerHTML = '<h1 class="om-page-title">Users</h1>';
      document.dispatchEvent(new CustomEvent("om:sidebar:active-change"));
      expect(Array.from(slot.querySelectorAll("li")).map((item) => item.textContent?.trim())).toEqual(["Authentication", "Users"]);
      expect(slot.querySelector("a")).toBeNull();

      // A title that repeats the group label ("Dashboard › Overview" on the Dashboard page) is not appended.
      document.querySelector("#oldman-main")!.innerHTML = '<h1 class="om-page-title">Authentication</h1>';
      document.dispatchEvent(new CustomEvent("om:sidebar:active-change"));
      expect(Array.from(slot.querySelectorAll("li")).map((item) => item.textContent?.trim())).toEqual(["Authentication", "Users"]);

      // Nothing active and no title: the slot and its separator disappear.
      document.querySelector("a.active")!.classList.remove("active");
      document.querySelector("#oldman-main")!.innerHTML = "";
      document.dispatchEvent(new CustomEvent("om:sidebar:active-change"));
      expect(slot.childElementCount).toBe(0);
      expect(document.querySelector<HTMLElement>("[data-om-topbar-breadcrumb-separator]")!.hidden).toBe(true);
    } finally {
      await topbar.stop();
    }
  });

  it("mirrors the page breadcrumb template into the topbar and follows main frame swaps", async () => {
    document.body.innerHTML = `
      <header id="page-topbar">
        <span data-om-topbar-breadcrumb-separator hidden></span>
        <nav data-om-topbar-breadcrumb></nav>
      </header>
      <turbo-frame id="oldman-main">
        <template data-om-breadcrumb><ol><li><a href="/admin">Administration</a></li><li><span aria-current="page">Users</span></li></ol></template>
      </turbo-frame>
    `;
    const topbar = new DashboardTopbar(document.body);
    await topbar.start();

    try {
      const slot = document.querySelector<HTMLElement>("[data-om-topbar-breadcrumb]")!;
      const separator = document.querySelector<HTMLElement>("[data-om-topbar-breadcrumb-separator]")!;
      expect(slot.querySelectorAll("li")).toHaveLength(2);
      expect(slot.querySelector("[aria-current='page']")?.textContent).toBe("Users");
      expect(separator.hidden).toBe(false);

      const frame = document.querySelector<HTMLElement>("#oldman-main")!;
      frame.innerHTML = `<template data-om-breadcrumb><ol><li><span aria-current="page">Projects</span></li></ol></template>`;
      frame.dispatchEvent(new Event("turbo:frame-render", { bubbles: true }));
      expect(slot.querySelector("[aria-current='page']")?.textContent).toBe("Projects");

      frame.innerHTML = "";
      frame.dispatchEvent(new Event("turbo:frame-render", { bubbles: true }));
      expect(slot.childElementCount).toBe(0);
      expect(separator.hidden).toBe(true);
    } finally {
      await topbar.stop();
    }
  });

  it("persists the theme toggle through the configured preference store", async () => {
    document.documentElement.setAttribute("data-theme", "light");
    document.body.innerHTML = '<header id="page-topbar"><button type="button" class="light-dark-mode">Theme</button></header>';
    const preferences = createPreferenceStore({ backend: "memory" });
    const topbar = new DashboardTopbar(document.body, { preferences });

    await topbar.start();
    try {
      document.body.querySelector<HTMLButtonElement>(".light-dark-mode")!.click();
      expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
      expect(preferences.get(DASHBOARD_THEME_PREFERENCE_KEY)).toBe("dark");

      document.body.querySelector<HTMLButtonElement>(".light-dark-mode")!.click();
      expect(preferences.get(DASHBOARD_THEME_PREFERENCE_KEY)).toBe("light");
    } finally {
      await topbar.stop();
      document.documentElement.removeAttribute("data-theme");
    }
  });

  it("toggles fullscreen and follows the page scroll with the topbar shadow", async () => {
    document.body.innerHTML = `
      <header id="page-topbar"></header>
      <button type="button" data-toggle="fullscreen"></button>
    `;
    Object.defineProperty(document.documentElement, "requestFullscreen", { configurable: true, value: vi.fn(async () => undefined) });
    Object.defineProperty(document, "fullscreenElement", { configurable: true, get: () => null });
    const topbar = new DashboardTopbar(document.body);

    await topbar.start();
    try {
      document.body.querySelector<HTMLButtonElement>('[data-toggle="fullscreen"]')!.click();
      expect(document.body.classList.contains("fullscreen-enable")).toBe(true);
      expect(document.documentElement.requestFullscreen).toHaveBeenCalledTimes(1);

      Object.defineProperty(window, "scrollY", { configurable: true, value: 80 });
      window.dispatchEvent(new Event("scroll"));
      expect(document.querySelector("#page-topbar")?.classList.contains("topbar-shadow")).toBe(true);

      Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
      window.dispatchEvent(new Event("scroll"));
      expect(document.querySelector("#page-topbar")?.classList.contains("topbar-shadow")).toBe(false);
    } finally {
      await topbar.stop();
      document.body.className = "";
    }
  });

  it("uses a neutral notification route unless a consumer configures one", () => {
    const neutral = new TestDashboardTopbar(document.body);
    const configured = new TestDashboardTopbar(document.body, { defaultNotificationHref: "/control" });

    expect(neutral.renderNotification({ title: "Notice" })).toContain('href="/"');
    expect(configured.renderNotification({ title: "Notice" })).toContain('href="/control"');
    expect(configured.renderNotification({ href: "/explicit", title: "Notice" })).toContain('href="/explicit"');
  });

  it("keeps runtime activity separate from persistent user notifications", async () => {
    document.body.innerHTML = `
      <span data-om-user-notification-count>8</span>
      <section data-om-user-notification-topbar>
        <div data-om-user-notification-slot>
          <a data-om-user-notification-preview data-om-user-notification-id="91">Persistent</a>
        </div>
      </section>
      <section data-om-activity-notifications>
        <div data-om-activity-notification-list>
          <div data-om-activity-notification-empty>Empty</div>
        </div>
        <span data-om-activity-notification-count>0</span>
        <div data-om-activity-notification-actions hidden>
          <span data-om-activity-notification-selection-count>0</span>
          <button data-om-activity-notification-delete-selected>Delete</button>
        </div>
      </section>
    `;
    const topbar = new DashboardTopbar(document.body);
    await topbar.start();

    document.dispatchEvent(new CustomEvent("om:notification:add", {
      detail: {
        description: '<img src=x onerror="bad">',
        href: '/safe?value="quoted"',
        icon: "ri-alert-line bad<script>",
        title: "<b>Activity</b>"
      }
    }));

    const activityItem = document.querySelector<HTMLElement>("[data-om-activity-notification-item]")!;
    expect(activityItem).not.toBeNull();
    expect(activityItem.textContent).toContain("<b>Activity</b>");
    expect(activityItem.querySelector("script, img")).toBeNull();
    expect(activityItem.querySelector("i")?.className).toBe("ri-alert-line");
    expect(document.querySelector("[data-om-user-notification-preview]")?.textContent).toBe("Persistent");
    expect(document.querySelector("[data-om-user-notification-count]")?.textContent).toBe("8");
    expect(document.querySelector("[data-om-activity-notification-count]")?.textContent).toBe("1");

    const checkbox = activityItem.querySelector<HTMLInputElement>("[data-om-activity-notification-select]")!;
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    expect(document.querySelector("[data-om-activity-notification-selection-count]")?.textContent).toBe("1");
    document.querySelector<HTMLElement>("[data-om-activity-notification-delete-selected]")!.click();
    expect(document.querySelector("[data-om-activity-notification-item]")).toBeNull();
    expect(document.querySelector("[data-om-user-notification-preview]")).not.toBeNull();
    expect(document.querySelector("[data-om-user-notification-count]")?.textContent).toBe("8");

    await topbar.stop();
  });
});
