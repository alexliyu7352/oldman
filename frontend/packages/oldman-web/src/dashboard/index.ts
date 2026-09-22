import { isSameSitePath } from "../core/http/urls";
import { BasePage, type BasePageComponentLoader, type OldmanAppOptions } from "../app/index";
import type { FeedbackAlertOptions } from "../components/feedback";
import {
  CleanupRegistry,
  Component,
  type ComponentOptions,
  type ResponseAction,
  type ResponseActionContext
} from "../core/index";
import {
  EventStreamClient,
  SESSION_INVALIDATED_EVENT,
  type StopEventStreamHandler
} from "../sse/index";
import Waves from "node-waves";
import { HistoryBack } from "../components/history-back";
import { DashboardBackToTop, type DashboardBackToTopOptions } from "./back-to-top";
import { DashboardFeedback } from "./feedback";
import { DashboardModal } from "./modal";
import { DashboardNotifications } from "./notifications";
import { DashboardSidebar, type DashboardSidebarOptions } from "./sidebar";
import { resolveInitialDashboardTheme } from "./theme";
import {
  DashboardTopbar,
  type DashboardTopbarNotificationDetail,
  type DashboardTopbarOptions
} from "./topbar";

export type DashboardComponentLoader = BasePageComponentLoader;
export type DashboardComponentLoaders = Record<string, DashboardComponentLoader>;

export interface DashboardPageOptions extends OldmanAppOptions {
  backToTopOptions?: DashboardBackToTopOptions;
  defaultSidebarSize?: string;
  historyBackOptions?: ComponentOptions;
  layoutAttributes?: Record<string, string>;
  sidebarOptions?: Omit<DashboardSidebarOptions, "mainFrameSelector">;
  topbarOptions?: DashboardTopbarOptions;
}

const DEFAULT_SIDEBAR_SIZE = "lg";
const DASHBOARD_ACTIVITY_ACTION = "dashboard_activity";
const USER_EVENTS_META_SELECTOR = 'meta[name="oldman-user-events-url"]';
const NOTIFICATION_DOM_SELECTOR = "[data-om-user-notification-topbar], [data-om-user-notification-center]";
const wavesInitializedBodies = new WeakSet<HTMLElement>();
const layoutInitializedRoots = new WeakSet<HTMLElement>();

export const DEFAULT_DASHBOARD_LAYOUT_ATTRIBUTES: Record<string, string> = {
  "data-body-image": "none",
  "data-layout": "vertical",
  "data-layout-position": "fixed",
  "data-layout-style": "default",
  "data-layout-width": "fluid",
  "data-preloader": "enable",
  "data-sidebar": "light",
  "data-sidebar-image": "none",
  "data-sidebar-size": DEFAULT_SIDEBAR_SIZE,
  "data-sidebar-visibility": "show",
  "data-theme": "light",
  "data-theme-colors": "default",
  "data-topbar": "light"
};

const DEFAULT_TRANSIENT_BODY_CLASSES = [
  "fullscreen-enable",
  "om-modal-open",
  "swal2-shown",
  "swal2-height-auto",
  "swal2-toast-shown"
];

export class DashboardPage extends BasePage {
  private readonly backToTopOptions: DashboardBackToTopOptions;
  private readonly dashboardLayoutAttributes: Record<string, string>;
  private readonly historyBackOptions: ComponentOptions;
  private readonly sidebarOptions: DashboardSidebarOptions;
  private readonly topbarOptions: DashboardTopbarOptions;
  private eventStream: EventStreamClient | null = null;
  private eventStreamHandlers: StopEventStreamHandler[] = [];
  private notifications: DashboardNotifications | null = null;
  private shellFeedback: DashboardFeedback | null = null;
  private readonly shellCleanup = new CleanupRegistry();

  constructor(options: DashboardPageOptions | HTMLElement = {}) {
    const normalizedOptions = options instanceof HTMLElement ? { root: options } : options;
    const { componentLoaders, transientBodyClasses, transientHtmlAttributes, ...baseOptions } = normalizedOptions;
    const defaultSidebarSize = normalizedOptions.defaultSidebarSize
      ?? normalizedOptions.sidebarOptions?.defaultSidebarSize
      ?? normalizedOptions.layoutAttributes?.["data-sidebar-size"]
      ?? DEFAULT_SIDEBAR_SIZE;
    const pageOptions: OldmanAppOptions = {
      ...baseOptions,
      transientBodyClasses: transientBodyClasses ?? DEFAULT_TRANSIENT_BODY_CLASSES,
      transientHtmlAttributes: transientHtmlAttributes ?? {}
    };
    if (componentLoaders) {
      pageOptions.componentLoaders = componentLoaders;
    }
    super(pageOptions);
    this.dashboardLayoutAttributes = {
      ...DEFAULT_DASHBOARD_LAYOUT_ATTRIBUTES,
      ...normalizedOptions.layoutAttributes,
      "data-sidebar-size": defaultSidebarSize
    };
    this.sidebarOptions = {
      ...normalizedOptions.sidebarOptions,
      defaultSidebarSize
    };
    this.topbarOptions = normalizedOptions.topbarOptions ?? {};
    this.backToTopOptions = normalizedOptions.backToTopOptions ?? {};
    this.historyBackOptions = normalizedOptions.historyBackOptions ?? {};
  }

  protected override async mountShellComponents(): Promise<void> {
    this.shellFeedback = this.createFeedback();
    await this.mountShellComponent(this.shellFeedback);
    this.feedback = this.shellFeedback;
    await this.mountShellComponent(this.createSidebar());
    await this.mountShellComponent(this.createTopbar());
    await this.mountShellComponent(this.createBackToTop());
    await this.mountShellComponent(this.createHistoryBack());

    if (this.root.querySelector(NOTIFICATION_DOM_SELECTOR)) {
      this.notifications = new DashboardNotifications(
        this,
        this.shellFeedback,
        this.root
      );
      const notifications = this.notifications;
      this.shellCleanup.add(() => notifications.stop());
      await this.notifications.mount();
    }
    this.signal.throwIfAborted();
    this.listen(window, "pagehide", () => this.closeUserEventStream());
    this.listen<PageTransitionEvent>(window, "pageshow", (event) => {
      if (event.persisted) this.rebuildUserEventStream();
    });
    this.listen(document, "om:i18n:change", () => this.rebuildUserEventStream());
    this.shellCleanup.add(() => this.closeUserEventStream());
    this.rebuildUserEventStream();
  }

  protected override async unmountShellComponents(): Promise<void> {
    // A failing component must not prevent the other shell resources from stopping.
    await this.shellCleanup.run(this.logger);
    this.notifications = null;
    this.feedback = null;
    this.shellFeedback = null;
  }

  protected override async prepareShell(): Promise<void> {
    this.applyLayoutAttributes();
  }

  protected override async afterContentMounted(root: ParentNode): Promise<void> {
    await super.afterContentMounted(root);
    this.signal.throwIfAborted();
    const body = document.body;
    if (wavesInitializedBodies.has(body)) return;
    Waves.init();
    wavesInitializedBodies.add(body);
  }

  protected override showMainFrameRequestError(): void {
    void this.shellFeedback?.alert({
      icon: "error",
      title: this.i18n.t("Request failed")
    });
  }

  override async handleResponseAction(
    action: ResponseAction,
    context: ResponseActionContext
  ): Promise<boolean> {
    if (action.action !== DASHBOARD_ACTIVITY_ACTION) {
      return super.handleResponseAction(action, context);
    }
    const { description, href, icon, time, title, tone } = action;
    if (typeof title !== "string") {
      throw new Error("Dashboard activity action requires a title");
    }
    for (const value of [description, href, icon, time, tone]) {
      if (value != null && typeof value !== "string") {
        throw new Error("Dashboard activity action fields must be strings");
      }
    }
    document.dispatchEvent(new CustomEvent<DashboardTopbarNotificationDetail>("om:notification:add", {
      detail: {
        title,
        ...(typeof description === "string" ? { description } : {}),
        ...(typeof href === "string" ? { href } : {}),
        ...(typeof icon === "string" ? { icon } : {}),
        ...(typeof time === "string" ? { time } : {}),
        ...(typeof tone === "string" ? { tone } : {})
      }
    }));
    return true;
  }

  protected createSidebar(): Component {
    return new DashboardSidebar(this.root, {
      ...this.sidebarOptions,
      page: this,
      i18n: this.i18n
    });
  }

  protected createTopbar(): Component {
    return new DashboardTopbar(this.root, {
      preferences: this.preferences,
      ...this.topbarOptions,
      page: this,
      i18n: this.i18n
    });
  }

  /** Create the shell-owned feedback instance shared by user event handlers. */
  protected createFeedback(): DashboardFeedback {
    return new DashboardFeedback(this.root, { page: this, i18n: this.i18n });
  }

  /** Register application-specific low-frequency handlers on the shared connection. */
  protected bindUserEventStream(_client: EventStreamClient): StopEventStreamHandler[] {
    return [];
  }

  /** Navigate after a validated Session or notification action. */
  protected navigate(url: string): void {
    window.location.assign(url);
  }

  protected createBackToTop(): Component {
    return new DashboardBackToTop(this.root, {
      ...this.backToTopOptions,
      page: this,
      i18n: this.i18n
    });
  }

  protected createHistoryBack(): Component {
    return new HistoryBack(this.root, {
      ...this.historyBackOptions,
      page: this,
      i18n: this.i18n
    });
  }

  private applyLayoutAttributes(): void {
    const html = document.documentElement;
    const initialized = layoutInitializedRoots.has(html);
    for (const [name, value] of Object.entries(this.dashboardLayoutAttributes)) {
      // These are initial defaults, not instructions to discard choices on every Page mount.
      if (initialized && (name === "data-theme" || name === "data-sidebar-size")) continue;
      html.setAttribute(name, value);
    }
    if (!initialized) {
      // A stored choice or the OS scheme beats the template default; later mounts keep the live value.
      html.setAttribute(
        "data-theme",
        resolveInitialDashboardTheme(this.preferences, this.dashboardLayoutAttributes["data-theme"])
      );
    }
    layoutInitializedRoots.add(html);
  }

  private async mountShellComponent(component: Component): Promise<void> {
    this.signal.throwIfAborted();
    // Register before awaiting start, so partial mounts receive their stop hooks too.
    this.shellCleanup.add(() => component.stop());
    await component.start();
    this.signal.throwIfAborted();
  }

  private rebuildUserEventStream(): void {
    this.closeUserEventStream();
    const url = this.userEventStreamUrl();
    if (url === null) return;

    const client = new EventStreamClient(url);
    this.eventStream = client;
    this.eventStreamHandlers = [
      client.on(SESSION_INVALIDATED_EVENT, (payload) => this.handleSessionInvalidated(payload)),
      ...(this.notifications?.bindEventStream(client) ?? []),
      ...this.bindUserEventStream(client)
    ];
  }

  private closeUserEventStream(): void {
    const handlers = this.eventStreamHandlers;
    this.eventStreamHandlers = [];
    for (const stop of handlers) stop();
    this.eventStream?.close();
    this.eventStream = null;
  }

  private userEventStreamUrl(): string | null {
    const metas = document.head.querySelectorAll<HTMLMetaElement>(USER_EVENTS_META_SELECTOR);
    if (metas.length === 0) return null;
    if (metas.length !== 1) {
      throw new Error("Expected exactly one oldman-user-events-url meta element");
    }
    const url = metas.item(0).content;
    if (!isSameSitePath(url)) {
      throw new Error("oldman-user-events-url must be a same-site absolute path");
    }
    return url;
  }

  private handleSessionInvalidated(payload: unknown): void {
    if (!isSessionInvalidatedPayload(payload)) {
      this.logger.error("Invalid oldman.session.invalidated payload", payload);
      return;
    }
    this.notifications?.stop();
    const feedback = this.shellFeedback;
    if (!feedback) return;
    const options = {
      icon: "warning",
      text: payload.message,
      titleText: payload.title
    };
    void feedback.alert(options as FeedbackAlertOptions).then((result) => {
      if (result.isConfirmed) this.navigate(payload.login_url);
    });
  }
}

function isSessionInvalidatedPayload(value: unknown): value is {
  login_url: string;
  message: string;
  title: string;
} {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  return isSameSitePath(payload.login_url)
    && typeof payload.message === "string"
    && typeof payload.title === "string";
}
export {
  DashboardBackToTop,
  DashboardFeedback,
  DashboardModal,
  DashboardNotifications,
  DashboardSidebar,
  DashboardTopbar
};
export { createDashboardComponentLoaders, createDashboardCrudComponentLoaders } from "./loaders";
export type { DashboardBackToTopOptions } from "./back-to-top";
export type { DashboardFeedbackOptions } from "./feedback";
export type { DashboardModalOptions } from "./modal";
export type {
  DashboardNotificationServices,
  NotificationCreatedPayload,
  NotificationPushPayload,
  UserNotificationPayload
} from "./notifications";
export type { DashboardSidebarOptions } from "./sidebar";
export type { DashboardTopbarNotificationDetail, DashboardTopbarOptions } from "./topbar";
