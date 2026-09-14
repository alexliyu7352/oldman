import { Component, type ComponentOptions } from "../core/index";

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

/** Manage local Dashboard activity without touching persistent user notifications. */
export class DashboardTopbar extends Component {
  private readonly customEmptyNotificationTemplate: (() => string) | null;
  private readonly defaultNotificationHref: string;
  private readonly topbarSelector: string;

  constructor(root: HTMLElement, options: DashboardTopbarOptions = {}) {
    super(root, options);
    this.customEmptyNotificationTemplate = options.emptyNotificationTemplate ?? null;
    this.defaultNotificationHref = options.defaultNotificationHref ?? "/";
    this.topbarSelector = options.topbarSelector ?? DEFAULT_TOPBAR_SELECTOR;
  }

  override async mount(): Promise<void> {
    this.bindTopbarShadow();
    this.bindFullscreen();
    this.bindThemeModeToggle();
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
      window.dispatchEvent(new Event("resize"));
    });
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
    const href = this.escapeHtml(detail.href || this.defaultNotificationHref);
    const title = this.escapeHtml(detail.title || this.i18n.t("Notification"));
    const description = this.escapeHtml(detail.description || "");
    const time = this.escapeHtml(detail.time || this.i18n.t("Just now"));
    const id = `runtime-notification-${Date.now()}-${Math.round(Math.random() * 100000)}`;

    return `
      <div data-om-activity-notification-item class="notification-item group relative rounded-lg px-2 py-2 transition-colors hover:bg-default-50">
        <div class="flex gap-3">
          <span class="om-notification-icon om-notification-icon-${tone}">
            <i class="${icon}"></i>
          </span>
          <div class="min-w-0 flex-1">
            <a href="${href}" class="block truncate text-sm font-medium text-default-900">${title}</a>
            <p class="mt-0.5 line-clamp-2 text-xs leading-5 text-default-500">${description}</p>
            <p class="mt-1 text-[0.6875rem] font-medium text-default-400">${time}</p>
          </div>
          <label class="notification-check flex shrink-0 items-start pt-1">
            <input data-om-activity-notification-select class="om-check notification-check-input" type="checkbox" value="" id="${id}">
            <span class="sr-only">${this.i18n.t("Select notification")}</span>
          </label>
        </div>
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

  protected escapeHtml(value: string): string {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
}
