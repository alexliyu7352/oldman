import type {
  FeedbackAlertOptions,
  FeedbackResult,
  FeedbackToastOptions
} from "../components/feedback";
import { normalizeHttpError, type Logger } from "../core/index";
import {
  type EventStreamClient,
  type StopEventStreamHandler
} from "../sse/index";
import type { DashboardPage } from "./index";
import { DashboardFeedback } from "./feedback";

export interface UserNotificationPayload {
  version: number;
  title: string;
  body: string | null;
  level: "success" | "info" | "warning" | "error";
  format: "text" | "html";
  presentation: "none" | "toast" | "modal";
  href: string | null;
  icon: string | null;
}

export interface NotificationCreatedPayload {
  notification_id: number;
  notification: UserNotificationPayload;
  created_at: string;
}

export interface NotificationPushPayload {
  notification: UserNotificationPayload;
}

export interface DashboardNotificationServices {
  http: DashboardPage["http"];
  i18n: DashboardPage["i18n"];
  logger: DashboardPage["logger"];
  mainFrameSelector: DashboardPage["mainFrameSelector"];
}

interface NotificationSyncPayload {
  changed_count: number;
}

interface TopbarContext {
  centerUrl: string;
  slot: HTMLElement;
  topbarUrl: string;
}

interface DefaultApiResponse {
  data: {
    changed: number;
  };
  error_code: number;
}

type NotificationAction = "all-read" | "delete-selected" | "selected-read";

const CREATED_EVENT = "oldman.notifications.created";
const PUSH_EVENT = "oldman.notifications.push";
const SYNC_EVENT = "oldman.notifications.sync";
const TOPBAR_SELECTOR = "[data-om-user-notification-topbar]";
const CENTER_SELECTOR = "[data-om-user-notification-center]";
const CENTER_ITEM_SELECTOR = "[data-om-user-notification-center-item]";
const SELECTOR = "[data-om-user-notification-select]";
const SELECTED_READ_SELECTOR = "[data-om-user-notification-mark-selected-read]";
const ALL_READ_SELECTOR = "[data-om-user-notification-mark-all-read]";
const DELETE_SELECTED_SELECTOR = "[data-om-user-notification-delete-selected]";
const REFRESH_CENTER_SELECTOR = "[data-om-user-notification-refresh-center]";
const RFC3339_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

/** Connect persistent notification DOM to the Dashboard's shared services. */
export class DashboardNotifications {
  private readonly controller = new AbortController();
  private refreshPromise: Promise<void> | null = null;
  private refreshQueued = false;
  private stopped = false;

  constructor(
    private readonly services: DashboardNotificationServices,
    private readonly feedback: DashboardFeedback,
    private readonly root: HTMLElement
  ) {}

  /** Bind root-level center controls and load the initial persistent preview. */
  async mount(): Promise<void> {
    if (this.stopped) throw new Error("DashboardNotifications has been stopped");
    this.root.addEventListener("change", this.handleChange, {
      signal: this.controller.signal
    });
    this.root.addEventListener("click", this.handleClick, {
      signal: this.controller.signal
    });
    this.root.addEventListener("turbo:frame-render", this.handleFrameRender, {
      signal: this.controller.signal
    });
    this.resetVisibleCenters();
    await this.refreshTopbar();
  }

  /** Abort adapter-owned work; the Dashboard remains owner of shared services. */
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.refreshQueued = false;
    this.controller.abort();
  }

  /** Register notification handlers on the Page-owned EventSource wrapper. */
  bindEventStream(client: EventStreamClient): StopEventStreamHandler[] {
    return [
      client.on(CREATED_EVENT, (payload) => this.consumeCreated(payload)),
      client.on(PUSH_EVENT, (payload) => this.consumePush(payload)),
      client.on(SYNC_EVENT, (payload) => this.consumeSync(payload)),
      client.onOpen(() => {
        void this.refreshTopbar();
      })
    ];
  }

  /** Refresh at most one request plus one coalesced newer request at a time. */
  refreshTopbar(): Promise<void> {
    if (this.stopped || !this.root.querySelector(TOPBAR_SELECTOR)) {
      return Promise.resolve();
    }
    if (this.refreshPromise) {
      this.refreshQueued = true;
      return this.refreshPromise;
    }

    this.refreshPromise = this.runRefreshLoop().finally(() => {
      this.refreshPromise = null;
    });
    return this.refreshPromise;
  }

  protected navigate(url: string): void {
    window.location.assign(url);
  }

  private async runRefreshLoop(): Promise<void> {
    do {
      this.refreshQueued = false;
      try {
        const context = this.topbarContext();
        const source = await this.services.http.html(context.topbarUrl, {
          redirectOnAuth: false,
          signal: this.controller.signal
        });
        if (this.stopped || this.refreshQueued) continue;
        this.applyTopbarFragment(context, source);
      } catch (error) {
        if (!this.stopped && normalizeHttpError(error).status !== 401) {
          this.services.logger.error("User notification topbar refresh failed", error);
        }
      }
    } while (this.refreshQueued && !this.stopped);
  }

  private topbarContext(): TopbarContext {
    const topbar = this.root.querySelector<HTMLElement>(TOPBAR_SELECTOR);
    const slot = topbar?.querySelector<HTMLElement>("[data-om-user-notification-slot]");
    const topbarUrl = topbar?.dataset.omTopbarUrl;
    const centerUrl = topbar?.dataset.omCenterUrl;
    if (
      !topbar ||
      !slot ||
      !isSameSitePath(topbarUrl) ||
      !isSameSitePath(centerUrl)
    ) {
      throw new Error("Invalid persistent notification topbar configuration");
    }
    return { centerUrl, slot, topbarUrl };
  }

  private applyTopbarFragment(context: TopbarContext, source: string): void {
    const template = document.createElement("template");
    template.innerHTML = source;
    const roots = template.content.querySelectorAll<HTMLElement>(
      "[data-om-user-notification-fragment]"
    );
    const fragment = roots.item(0);
    if (
      roots.length !== 1 ||
      template.content.children.length !== 1 ||
      template.content.firstElementChild !== fragment
    ) {
      throw new Error("Notification topbar response must contain one fragment root");
    }
    const rawCount = fragment.dataset.omUnreadCount;
    if (!rawCount || !/^(?:0|[1-9]\d*)$/.test(rawCount)) {
      throw new Error("Notification topbar unread count is invalid");
    }
    const unreadCount = Number(rawCount);
    if (!Number.isSafeInteger(unreadCount)) {
      throw new Error("Notification topbar unread count is invalid");
    }

    context.slot.replaceChildren(...fragment.childNodes);
    for (const counter of this.root.querySelectorAll<HTMLElement>(
      "[data-om-user-notification-count]"
    )) {
      counter.textContent = String(unreadCount);
      counter.hidden = unreadCount === 0;
    }
  }

  private consumeCreated(payload: unknown): void {
    const created = parseCreated(payload);
    if (!created) {
      this.invalidEvent(CREATED_EVENT, payload);
      return;
    }
    void this.handleCreated(created);
  }

  private consumePush(payload: unknown): void {
    const push = parsePush(payload);
    if (!push) {
      this.invalidEvent(PUSH_EVENT, payload);
      return;
    }
    void this.showNotification(push.notification, push.notification.href);
  }

  private consumeSync(payload: unknown): void {
    const sync = parseSync(payload);
    if (!sync) {
      this.invalidEvent(SYNC_EVENT, payload);
      return;
    }
    this.markCenterUpdateAvailable();
    void this.refreshTopbar();
  }

  private async handleCreated(payload: NotificationCreatedPayload): Promise<void> {
    const centerUrl = this.notificationCenterUrl();
    const actionUrl = payload.notification.href && centerUrl
      ? `${centerUrl}/${payload.notification_id}/open`
      : null;
    const shown = this.showNotification(payload.notification, actionUrl);
    this.markCenterUpdateAvailable();
    await this.refreshTopbar();
    await shown;
  }

  private async showNotification(
    notification: UserNotificationPayload,
    actionUrl: string | null
  ): Promise<void> {
    if (this.stopped || notification.presentation === "none") return;
    if (notification.presentation === "toast") {
      const options: FeedbackToastOptions = {
        icon: notification.level,
        titleText: notification.title,
        ...(actionUrl ? { onClick: () => {
          if (!this.stopped) this.navigate(actionUrl);
        } } : {})
      };
      if (notification.body !== null) {
        if (notification.format === "html") options.html = notification.body;
        else options.text = notification.body;
      }
      await this.feedback.toast(options);
      return;
    }

    const tone = notification.level === "error" ? "danger" : notification.level;
    const options = {
      customClass: { icon: `om-notification-icon-${tone}` },
      icon: notification.level,
      titleText: notification.title
    } as FeedbackAlertOptions;
    if (notification.body !== null) {
      if (notification.format === "html") options.html = notification.body;
      else options.text = notification.body;
    }
    if (actionUrl) {
      options.confirmButtonText = this.services.i18n.t("Open");
      options.showCancelButton = true;
      options.showConfirmButton = true;
    }

    const result: FeedbackResult = await this.feedback.alert(options);
    if (!this.stopped && actionUrl && result.isConfirmed) this.navigate(actionUrl);
  }

  private invalidEvent(eventName: string, payload: unknown): void {
    this.services.logger.error(`Invalid ${eventName} payload`, payload);
  }

  private notificationCenterUrl(): string | null {
    const topbarUrl = this.root.querySelector<HTMLElement>(TOPBAR_SELECTOR)
      ?.dataset.omCenterUrl;
    if (isSameSitePath(topbarUrl)) return topbarUrl;
    const centerUrl = this.root.querySelector<HTMLElement>(CENTER_SELECTOR)
      ?.dataset.omCenterUrl;
    return isSameSitePath(centerUrl) ? centerUrl : null;
  }

  private markCenterUpdateAvailable(): void {
    if (this.stopped) return;
    for (const button of this.root.querySelectorAll<HTMLElement>(
      `${CENTER_SELECTOR} ${REFRESH_CENTER_SELECTOR}`
    )) {
      button.hidden = false;
    }
  }

  private readonly handleChange = (event: Event): void => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement) || !target.matches(SELECTOR)) return;
    const center = target.closest<HTMLElement>(CENTER_SELECTOR);
    if (center && this.root.contains(center)) this.updateSelection(center);
  };

  private readonly handleClick = (event: Event): void => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const trigger = target.closest<HTMLElement>(
      `${SELECTED_READ_SELECTOR}, ${ALL_READ_SELECTOR}, ${DELETE_SELECTED_SELECTOR}, ${REFRESH_CENTER_SELECTOR}`
    );
    const center = trigger?.closest<HTMLElement>(CENTER_SELECTOR);
    if (!trigger || !center || !this.root.contains(center)) return;
    event.preventDefault();

    if (trigger.matches(REFRESH_CENTER_SELECTOR)) {
      this.reloadCenter(center);
      return;
    }
    if (trigger.matches(SELECTED_READ_SELECTOR)) {
      void this.mutate(center, trigger, "selected-read");
    } else if (trigger.matches(ALL_READ_SELECTOR)) {
      void this.mutate(center, trigger, "all-read");
    } else {
      void this.mutate(center, trigger, "delete-selected");
    }
  };

  private readonly handleFrameRender = (event: Event): void => {
    const frame = event.target;
    if (!(frame instanceof Element) || !frame.matches(this.services.mainFrameSelector)) return;
    for (const center of frame.querySelectorAll<HTMLElement>(CENTER_SELECTOR)) {
      this.resetCenter(center);
    }
  };

  private async mutate(
    center: HTMLElement,
    trigger: HTMLElement,
    action: NotificationAction
  ): Promise<void> {
    if (this.stopped) return;
    const ids = this.selectedIds(center);
    if (action !== "all-read" && ids.length === 0) return;
    if (
      action === "delete-selected" &&
      !(await this.feedback.confirm({
        icon: "warning",
        text: this.services.i18n.t("Selected notifications will be deleted."),
        title: this.services.i18n.t("Delete selected")
      }))
    ) {
      return;
    }
    if (this.stopped) return;

    const url = action === "delete-selected"
      ? center.dataset.omDeleteUrl
      : center.dataset.omReadUrl;
    if (!isSameSitePath(url)) {
      await this.reportMutationError(new Error("Invalid notification action URL"));
      return;
    }
    const body = action === "all-read" ? { all: true } : { ids };
    const button = trigger instanceof HTMLButtonElement ? trigger : null;
    if (button) button.disabled = true;
    try {
      const response = await this.services.http.postJson<unknown>(url, body, {
        signal: this.controller.signal
      });
      if (this.stopped) return;
      if (!parseApiResponse(response)) {
        throw new Error("Invalid notification API response");
      }
      await this.refreshTopbar();
      if (!this.stopped) this.reloadCenter(center);
    } catch (error) {
      if (!this.stopped) await this.reportMutationError(error);
    } finally {
      if (button && !this.stopped) {
        button.disabled = false;
        this.updateSelection(center);
      }
    }
  }

  private async reportMutationError(error: unknown): Promise<void> {
    this.services.logger.error("User notification operation failed", error);
    await this.feedback.alert({
      icon: "error",
      text: error instanceof Error ? error.message : this.services.i18n.t("Request failed"),
      title: this.services.i18n.t("Request failed")
    });
  }

  private selectedIds(center: HTMLElement): number[] {
    const ids = new Set<number>();
    for (const input of center.querySelectorAll<HTMLInputElement>(
      `${SELECTOR}:checked`
    )) {
      const item = input.closest<HTMLElement>(CENTER_ITEM_SELECTOR);
      const rawId = item?.dataset.omUserNotificationId;
      if (!rawId || !/^[1-9]\d*$/.test(rawId)) continue;
      const notificationId = Number(rawId);
      if (Number.isSafeInteger(notificationId)) ids.add(notificationId);
    }
    return [...ids];
  }

  private updateSelection(center: HTMLElement): void {
    const count = this.selectedIds(center).length;
    const output = center.querySelector<HTMLElement>(
      "[data-om-user-notification-selection-count]"
    );
    if (output) output.textContent = String(count);
    for (const button of center.querySelectorAll<HTMLButtonElement>(
      `${SELECTED_READ_SELECTOR}, ${DELETE_SELECTED_SELECTOR}`
    )) {
      button.disabled = count === 0;
    }
  }

  private resetVisibleCenters(): void {
    for (const center of this.root.querySelectorAll<HTMLElement>(CENTER_SELECTOR)) {
      this.resetCenter(center);
    }
  }

  private resetCenter(center: HTMLElement): void {
    for (const input of center.querySelectorAll<HTMLInputElement>(SELECTOR)) {
      input.checked = false;
    }
    const refresh = center.querySelector<HTMLElement>(REFRESH_CENTER_SELECTOR);
    if (refresh) refresh.hidden = true;
    this.updateSelection(center);
  }

  private reloadCenter(center: HTMLElement): void {
    const currentUrl = center.dataset.omCurrentUrl;
    if (!isSameSitePath(currentUrl)) {
      void this.reportMutationError(new Error("Invalid notification center URL"));
      return;
    }
    const frame = this.root.querySelector<HTMLElement>(this.services.mainFrameSelector);
    if (!frame) {
      void this.reportMutationError(new Error("Notification center frame was not found"));
      return;
    }
    const reload = (frame as HTMLElement & { reload?: () => void }).reload;
    if (frame.getAttribute("src") === currentUrl && typeof reload === "function") {
      reload.call(frame);
    } else {
      frame.setAttribute("src", currentUrl);
    }
  }
}

function parseCreated(value: unknown): NotificationCreatedPayload | null {
  if (!isRecord(value)) return null;
  const notificationId = value.notification_id;
  const createdAt = value.created_at;
  const notification = parseNotification(value.notification);
  if (
    !isPositiveInteger(notificationId) ||
    typeof createdAt !== "string" ||
    !RFC3339_PATTERN.test(createdAt) ||
    Number.isNaN(Date.parse(createdAt)) ||
    !notification
  ) {
    return null;
  }
  return {
    created_at: createdAt,
    notification,
    notification_id: notificationId
  };
}

function parsePush(value: unknown): NotificationPushPayload | null {
  if (!isRecord(value)) return null;
  const notification = parseNotification(value.notification);
  return notification ? { notification } : null;
}

function parseSync(value: unknown): NotificationSyncPayload | null {
  if (!isRecord(value) || !isNonNegativeInteger(value.changed_count)) return null;
  return { changed_count: value.changed_count };
}

function parseNotification(value: unknown): UserNotificationPayload | null {
  if (!isRecord(value)) return null;
  const { body, format, href, icon, level, presentation, title, version } = value;
  if (
    version !== 1 ||
    typeof title !== "string" ||
    !(body === null || typeof body === "string") ||
    !isOneOf(level, ["success", "info", "warning", "error"] as const) ||
    !isOneOf(format, ["text", "html"] as const) ||
    !isOneOf(presentation, ["none", "toast", "modal"] as const) ||
    !(href === null || isSameSitePath(href)) ||
    !(icon === null || typeof icon === "string")
  ) {
    return null;
  }
  return { body, format, href, icon, level, presentation, title, version };
}

function parseApiResponse(value: unknown): DefaultApiResponse | null {
  if (!isRecord(value) || value.error_code !== 0 || !isRecord(value.data)) {
    return null;
  }
  const changed = value.data.changed;
  if (!isNonNegativeInteger(changed)) return null;
  return { data: { changed }, error_code: 0 };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && typeof value === "number" && value > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && typeof value === "number" && value >= 0;
}

function isOneOf<T extends string>(value: unknown, choices: readonly T[]): value is T {
  return typeof value === "string" && choices.includes(value as T);
}

function isSameSitePath(value: unknown): value is string {
  return typeof value === "string"
    && value.startsWith("/")
    && !value.startsWith("//")
    && !value.includes("\\")
    && !/[\u0000-\u001f\u007f]/.test(value);
}
