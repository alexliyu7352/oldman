import { Component, type ComponentOptions, escapeHtml } from "../core/index";
import type { PreferenceStore } from "../core/services/preferences";
import { SIDEBAR_ACTIVE_CHANGE_EVENT } from "./sidebar";
import { isDashboardTheme, storeDashboardTheme } from "./theme";

export interface DashboardTopbarNotificationDetail {
  description?: string;
  href?: string;
  icon?: string;
  time?: string;
  title?: string;
  tone?: string;
}

export interface DashboardTopbarOptions extends ComponentOptions {
  defaultNotificationHref?: string;
  emptyNotificationTemplate?: () => string;
  /** Store that remembers the theme toggle across page loads; omit to keep the choice in-document only. */
  preferences?: PreferenceStore;
  topbarSelector?: string;
}

const ACTIVITY_SECTION_SELECTOR = "[data-om-activity-notifications]";
const ACTIVITY_LIST_SELECTOR = "[data-om-activity-notification-list]";
const ACTIVITY_ITEM_SELECTOR = "[data-om-activity-notification-item]";
const ACTIVITY_SELECT_SELECTOR = "[data-om-activity-notification-select]";
const ACTIVITY_ACTIONS_SELECTOR = "[data-om-activity-notification-actions]";
const ACTIVITY_DELETE_SELECTOR = "[data-om-activity-notification-delete-selected]";
const ACTIVITY_SELECTION_COUNT_SELECTOR = "[data-om-activity-notification-selection-count]";
const ACTIVITY_COUNT_SELECTOR = "[data-om-activity-notification-count]";
const ACTIVITY_EMPTY_SELECTOR = "[data-om-activity-notification-empty], .empty-notification-elem";
const ACTIVITY_VIEW_ALL_SELECTOR = "[data-om-activity-view-all]";
const DEFAULT_NOTIFICATION_DROPDOWN_SELECTOR = "#notificationDropdown";
const DEFAULT_TOPBAR_SELECTOR = "#page-topbar";
const MAIN_FRAME_SELECTOR = "turbo-frame#oldman-main";
const BREADCRUMB_SOURCE_SELECTOR = "template[data-om-breadcrumb]";
const BREADCRUMB_SLOT_SELECTOR = "[data-om-topbar-breadcrumb]";
const BREADCRUMB_SEPARATOR_SELECTOR = "[data-om-topbar-breadcrumb-separator]";
const SIDEBAR_SELECTOR = "[data-om-sidebar]";
const PAGE_TITLE_SELECTOR = ".om-page-title";

interface BreadcrumbEntry {
  href?: string;
  label: string;
}

/** Manage local Dashboard activity without touching persistent user notifications. */
export class DashboardTopbar extends Component {
  private readonly customEmptyNotificationTemplate: (() => string) | null;
  private readonly defaultNotificationHref: string;
  private readonly preferences: PreferenceStore | null;
  private readonly topbarSelector: string;

  constructor(root: HTMLElement, options: DashboardTopbarOptions = {}) {
    super(root, options);
    this.customEmptyNotificationTemplate = options.emptyNotificationTemplate ?? null;
    this.defaultNotificationHref = options.defaultNotificationHref ?? "/";
    this.preferences = options.preferences ?? null;
    this.topbarSelector = options.topbarSelector ?? DEFAULT_TOPBAR_SELECTOR;
  }

  override async mount(): Promise<void> {
    this.bindTopbarShadow();
    this.bindFullscreen();
    this.bindThemeModeToggle();
    this.bindBreadcrumb();
    this.bindActivitySelection();
    this.bindActivityEvents();
    this.refreshActivityState();
  }

  override async beforeUnmount(): Promise<void> {
    document.body.classList.remove("fullscreen-enable");
  }

  private bindTopbarShadow(): void {
    const updateShadow = () => {
      const header = this.root.querySelector<HTMLElement>(this.topbarSelector);
      if (!header) return;
      header.classList.toggle("topbar-shadow", window.scrollY > 50);
    };
    this.listen(window, "scroll", updateShadow);
    updateShadow();
  }

  private bindFullscreen(): void {
    this.on("click", '[data-toggle="fullscreen"]', (event) => {
      event.preventDefault();
      document.body.classList.toggle("fullscreen-enable");
      if (!document.fullscreenElement) {
        void document.documentElement.requestFullscreen?.().catch(() => undefined);
      } else {
        void document.exitFullscreen?.().catch(() => undefined);
      }
    });

    this.listen(document, "fullscreenchange", () => {
      if (!document.fullscreenElement) document.body.classList.remove("fullscreen-enable");
    });
  }

  private bindThemeModeToggle(): void {
    this.on("click", ".light-dark-mode", (event) => {
      event.preventDefault();
      const html = document.documentElement;
      const next = html.getAttribute("data-theme") === "dark" ? "light" : "dark";
      html.setAttribute("data-theme", next);
      if (this.preferences && isDashboardTheme(next)) storeDashboardTheme(this.preferences, next);
      window.dispatchEvent(new Event("resize"));
    });
  }

  /**
   * The topbar lives outside the main Turbo frame. A page may publish an explicit breadcrumb in a
   * <template data-om-breadcrumb>; otherwise the topbar derives one from the shell (sidebar group,
   * active menu item, page title) after every frame swap and sidebar activation.
   */
  private bindBreadcrumb(): void {
    this.listen(document, "turbo:frame-render", (event) => {
      const target = event.target;
      if (target instanceof Element && target.matches(MAIN_FRAME_SELECTOR)) this.syncBreadcrumb();
    });
    this.listen(document, SIDEBAR_ACTIVE_CHANGE_EVENT, () => this.syncBreadcrumb());
    this.syncBreadcrumb();
  }

  private syncBreadcrumb(): void {
    const header = this.root.querySelector<HTMLElement>(this.topbarSelector);
    const slot = header?.querySelector<HTMLElement>(BREADCRUMB_SLOT_SELECTOR);
    if (!slot) return;
    const source = this.root.querySelector<HTMLTemplateElement>(`${MAIN_FRAME_SELECTOR} ${BREADCRUMB_SOURCE_SELECTOR}`)
      ?? this.root.querySelector<HTMLTemplateElement>(BREADCRUMB_SOURCE_SELECTOR);
    const crumbs = source ? source.content.cloneNode(true) : this.buildBreadcrumbFromShell();
    slot.replaceChildren(...(crumbs ? [crumbs] : []));
    const separator = header?.querySelector<HTMLElement>(BREADCRUMB_SEPARATOR_SELECTOR);
    if (separator) separator.hidden = !crumbs;
  }

  /** Sidebar group › active menu item › page title; entries collapse when labels repeat. */
  private buildBreadcrumbFromShell(): HTMLOListElement | null {
    const entries: BreadcrumbEntry[] = [];
    const activeLink = this.root.querySelector<HTMLAnchorElement>(`${SIDEBAR_SELECTOR} a.active`);
    if (activeLink) {
      const rootItem = activeLink.closest<HTMLElement>("[data-om-menu-item]");
      const groupLabel = textOf(rootItem?.querySelector<HTMLElement>(":scope > [data-om-menu-toggle] .menu-text"));
      if (groupLabel) entries.push({ label: groupLabel });
      const itemLabel = textOf(activeLink.querySelector<HTMLElement>(".menu-text")) || textOf(activeLink);
      const href = activeLink.getAttribute("href");
      if (itemLabel) entries.push(href ? { href, label: itemLabel } : { label: itemLabel });
    }
    const title = textOf(
      this.root.querySelector<HTMLElement>(`${MAIN_FRAME_SELECTOR} ${PAGE_TITLE_SELECTOR}`)
        ?? this.root.querySelector<HTMLElement>(PAGE_TITLE_SELECTOR)
    );
    if (title && !entries.some((entry) => entry.label === title)) entries.push({ label: title });
    if (entries.length === 0) return null;

    const list = document.createElement("ol");
    list.className = "oldman-breadcrumb";
    entries.forEach((entry, index) => {
      const item = document.createElement("li");
      const last = index === entries.length - 1;
      if (!last && entry.href) {
        const link = document.createElement("a");
        link.href = entry.href;
        link.textContent = entry.label;
        item.append(link);
      } else {
        const text = document.createElement("span");
        if (last) text.setAttribute("aria-current", "page");
        text.textContent = entry.label;
        item.append(text);
      }
      list.append(item);
    });
    return list;
  }

  private bindActivitySelection(): void {
    this.on("change", ACTIVITY_SELECT_SELECTOR, (_event, trigger) => {
      const input = trigger as HTMLInputElement;
      input.closest(ACTIVITY_ITEM_SELECTOR)?.classList.toggle("active", input.checked);
      this.updateActivitySelection();
    });

    this.on("click", ACTIVITY_DELETE_SELECTOR, (event) => {
      event.preventDefault();
      for (const item of this.$$(ACTIVITY_ITEM_SELECTOR)) {
        const input = item.querySelector<HTMLInputElement>(ACTIVITY_SELECT_SELECTOR);
        if (input?.checked) item.remove();
      }
      this.refreshActivityState();
      this.updateActivitySelection();
      this.root.querySelector<HTMLElement>("#NotificationModalbtn-close")?.click();
    });

    this.listen(document, "click", (event) => {
      const target = event.target;
      if (
        target instanceof Element
        && target.closest(DEFAULT_NOTIFICATION_DROPDOWN_SELECTOR)
      ) {
        return;
      }
      this.clearActivitySelection();
    });
  }

  private bindActivityEvents(): void {
    this.listen<CustomEvent<DashboardTopbarNotificationDetail>>(
      document,
      "om:notification:add",
      (event) => this.addActivity(event.detail ?? {})
    );
  }

  private addActivity(detail: DashboardTopbarNotificationDetail): void {
    const list = this.root.querySelector<HTMLElement>(ACTIVITY_LIST_SELECTOR);
    if (!list) return;
    for (const empty of list.querySelectorAll(ACTIVITY_EMPTY_SELECTOR)) empty.remove();

    const viewAll = list.querySelector<HTMLElement>(ACTIVITY_VIEW_ALL_SELECTOR);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = this.notificationTemplate(detail);
    const item = wrapper.firstElementChild;
    if (item) list.insertBefore(item, viewAll);
    if (viewAll) viewAll.hidden = false;
    this.refreshActivityState();
    this.updateActivitySelection();
  }

  private refreshActivityState(): void {
    const section = this.root.querySelector<HTMLElement>(ACTIVITY_SECTION_SELECTOR);
    const list = section?.querySelector<HTMLElement>(ACTIVITY_LIST_SELECTOR);
    if (!section || !list) return;

    const count = list.querySelectorAll(ACTIVITY_ITEM_SELECTOR).length;
    for (const counter of section.querySelectorAll<HTMLElement>(ACTIVITY_COUNT_SELECTOR)) {
      counter.textContent = String(count);
    }
    const viewAll = list.querySelector<HTMLElement>(ACTIVITY_VIEW_ALL_SELECTOR);
    if (viewAll) viewAll.hidden = count === 0;

    if (count === 0 && !list.querySelector(ACTIVITY_EMPTY_SELECTOR)) {
      const template = this.emptyNotificationTemplate();
      if (template) list.insertAdjacentHTML("beforeend", template);
    }
  }

  private updateActivitySelection(): void {
    const section = this.root.querySelector<HTMLElement>(ACTIVITY_SECTION_SELECTOR);
    if (!section) return;
    const checkedCount = section.querySelectorAll(`${ACTIVITY_SELECT_SELECTOR}:checked`).length;
    const actions = section.querySelector<HTMLElement>(ACTIVITY_ACTIONS_SELECTOR);
    const output = section.querySelector<HTMLElement>(ACTIVITY_SELECTION_COUNT_SELECTOR);
    if (actions) actions.hidden = checkedCount === 0;
    if (output) output.textContent = String(checkedCount);
  }

  private clearActivitySelection(): void {
    const section = this.root.querySelector<HTMLElement>(ACTIVITY_SECTION_SELECTOR);
    if (!section) return;
    for (const input of section.querySelectorAll<HTMLInputElement>(ACTIVITY_SELECT_SELECTOR)) {
      input.checked = false;
    }
    for (const item of section.querySelectorAll<HTMLElement>(ACTIVITY_ITEM_SELECTOR)) {
      item.classList.remove("active");
    }
    this.updateActivitySelection();
  }

  protected notificationTemplate(detail: DashboardTopbarNotificationDetail): string {
    const tone = this.safeToken(detail.tone || "primary", "primary");
    const icon = this.safeIcon(detail.icon || "ri-user-settings-line");
    const href = escapeHtml(detail.href || this.defaultNotificationHref);
    const title = escapeHtml(detail.title || this.i18n.t("Notification"));
    const description = escapeHtml(detail.description || "");
    const time = escapeHtml(detail.time || this.i18n.t("Just now"));
    const id = `runtime-notification-${Date.now()}-${Math.round(Math.random() * 100000)}`;

    return `
      <div data-om-activity-notification-item class="notification-item om-notification-item group">
        <span class="om-notification-icon om-notification-icon-${tone}">
          <i class="${icon}"></i>
        </span>
        <div class="min-w-0 flex-1">
          <a href="${href}" class="om-notification-title">${title}</a>
          <p class="om-notification-body">${description}</p>
          <p class="om-notification-time">${time}</p>
        </div>
        <label class="notification-check flex shrink-0 items-start pt-1">
          <input data-om-activity-notification-select class="om-check notification-check-input" type="checkbox" value="" id="${id}">
          <span class="sr-only">${this.i18n.t("Select notification")}</span>
        </label>
      </div>
    `;
  }

  protected emptyNotificationTemplate(): string {
    return this.customEmptyNotificationTemplate?.() ?? "";
  }

  private safeToken(value: string, fallback: string): string {
    return /^[a-z0-9_-]+$/i.test(value) ? value : fallback;
  }

  private safeIcon(value: string): string {
    return value
      .split(/\s+/)
      .filter((item) => /^[a-z0-9_-]+$/i.test(item))
      .join(" ") || "ri-user-settings-line";
  }

}

function textOf(element: Element | null | undefined): string {
  return (element?.textContent ?? "").trim();
}
