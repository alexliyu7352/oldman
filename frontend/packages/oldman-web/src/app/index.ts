import { Page, ScopedPreloader, queryAllSelfOrDescendants, type ComponentConstructor } from "../core/index";

export type BasePageComponentLoader = () => Promise<ComponentConstructor>;
export type MainFrameState = "loading" | "rendering" | "mounting" | "mounted" | "failed";

export interface OldmanAppOptions {
  componentLoaders?: Record<string, BasePageComponentLoader>;
  decorateDropdowns?: boolean;
  decorateScrollAreas?: boolean;
  initialLoadingSelector?: string;
  mainFrameSelector?: string;
  overlayCleanupSelectors?: string;
  refreshIcons?: (root: ParentNode) => void | Promise<void>;
  root?: HTMLElement;
  transientBodyClasses?: string[];
  transientHtmlAttributes?: Record<string, string>;
}

type TurboFrameMissingDetail = {
  response?: Response;
  visit?: (response: Response) => void | Promise<void>;
};

type TurboFetchRequestDetail = {
  visit?: {
    action?: string;
  };
};

type TurboFetchResponseDetail = {
  fetchResponse?: { failed: boolean; isHTML: boolean };
};

type DynamicContentMountDetail = {
  root?: ParentNode;
  waitUntil?: (promise: Promise<void>) => void;
};

const DEFAULT_INITIAL_LOADING_SELECTOR = "[data-om-loading-initial='true']";
const DEFAULT_OVERLAY_CLEANUP_SELECTORS = "[data-om-modal-backdrop], .swal2-container";

export class BasePage extends Page {
  private readonly componentLoaders: Record<string, BasePageComponentLoader>;
  private readonly decorateDropdowns: boolean;
  private readonly decorateScrollAreasEnabled: boolean;
  private readonly initialLoadingSelector: string;
  private readonly overlayCleanupSelectors: string;
  private readonly refreshIconsCallback: ((root: ParentNode) => void | Promise<void>) | null;
  private readonly transientBodyClasses: string[];
  private readonly transientHtmlAttributes: Record<string, string>;
  private initialLoadingPreloaders = new Map<HTMLElement, ScopedPreloader>();
  private mainFramePreloader: ScopedPreloader | null = null;

  constructor(options: OldmanAppOptions = {}) {
    super(options.root ?? document.documentElement, options.mainFrameSelector);
    this.componentLoaders = options.componentLoaders ?? {};
    this.decorateDropdowns = options.decorateDropdowns ?? true;
    this.decorateScrollAreasEnabled = options.decorateScrollAreas ?? true;
    this.initialLoadingSelector = options.initialLoadingSelector ?? DEFAULT_INITIAL_LOADING_SELECTOR;
    this.overlayCleanupSelectors = options.overlayCleanupSelectors ?? DEFAULT_OVERLAY_CLEANUP_SELECTORS;
    this.refreshIconsCallback = options.refreshIcons ?? null;
    this.transientBodyClasses = options.transientBodyClasses ?? [];
    this.transientHtmlAttributes = options.transientHtmlAttributes ?? {};
    // Registry runs these even when a Page hook or ordinary component fails to stop.
    // Cleanup is LIFO: release the shell before clearing its transient DOM state.
    this.cleanup(() => this.clearTransientPageState());
    this.cleanup(() => this.unmountShellComponents());
  }

  override async mount(): Promise<void> {
    this.signal.throwIfAborted();
    this.clearTransientPageState();
    await this.prepareShell();
    this.signal.throwIfAborted();
    await this.mountDeclarativePreloader();
    this.signal.throwIfAborted();
    await this.mountShellComponents();
    this.signal.throwIfAborted();
    const mainFrame = this.root.querySelector<HTMLElement>(this.mainFrameSelector);
    if (mainFrame) {
      this.installMainFrameLifecycle();
      // Turbo can snapshot the initial document before any frame request creates this scope.
      this.preloaderForMainFrame(mainFrame).hide();
    }
    this.decorateContent(this.root);
    this.installInitialLoadingLifecycle();
    this.installDynamicContentLifecycle();
    this.showInitialLoadingScopes(this.root);
    await this.registerDeclarativeComponents(this.root);
    this.signal.throwIfAborted();
    await this.components.mount(this.root);
    this.signal.throwIfAborted();
    this.setMainFrameState("mounted");
    await this.afterContentMounted(this.root);
    this.signal.throwIfAborted();
  }

  override async beforeUnmount(): Promise<void> {
    this.clearInitialLoadingScopes(this.root);
  }

  protected async mountShellComponents(): Promise<void> {}

  protected async unmountShellComponents(): Promise<void> {}

  protected async prepareShell(): Promise<void> {}

  protected async afterContentMounted(root: ParentNode): Promise<void> {
    this.setCounterValues(root);
    await this.refreshIcons(root);
  }

  /** Let the application shell present a failed main-frame navigation. */
  protected showMainFrameRequestError(): void {}

  protected async refreshIcons(root: ParentNode = this.root): Promise<void> {
    await this.refreshIconsCallback?.(root);
    this.signal.throwIfAborted();
  }

  protected setCounterValues(root: ParentNode = this.root): void {
    const counters = queryAllSelfOrDescendants<HTMLElement>(root, ".counter-value[data-target]");
    for (const counter of counters) {
      const target = counter.getAttribute("data-target");
      if (!target) continue;

      const numericTarget = Number(target);
      counter.textContent = Number.isInteger(numericTarget) ? numericTarget.toLocaleString() : target;
    }
  }

  protected clearTransientPageState(): void {
    document.body.classList.remove(...this.transientBodyClasses);
    document.body.style.removeProperty("overflow");
    document.body.style.removeProperty("padding-right");

    for (const [name, value] of Object.entries(this.transientHtmlAttributes)) {
      document.documentElement.setAttribute(name, value);
    }

    for (const overlay of document.querySelectorAll<HTMLElement>(this.overlayCleanupSelectors)) {
      overlay.remove();
    }
  }

  protected decorateContent(root: ParentNode = this.root): void {
    if (this.decorateScrollAreasEnabled) this.decorateScrollAreas(root);
    if (this.decorateDropdowns) this.decorateLegacyDropdowns(root);
  }

  private async mountDeclarativePreloader(): Promise<void> {
    const preloader = this.root.querySelector<HTMLElement>("#preloader[data-om-component='preloader']");
    if (!preloader) return;
    await this.registerComponentLoader("preloader");
    await this.components.mount(preloader);
  }

  private installMainFrameLifecycle(): void {
    this.listen(document, "turbo:before-fetch-request", (event) => {
      const frame = this.mainFrameFromEventTarget(event.target);
      if (!frame) return;
      if (this.isRestorationFetch(event)) {
        this.hideMainFrameLoading(frame);
        return;
      }

      this.setMainFrameState("loading", frame);
      this.preloaderForMainFrame(frame).show(this.i18n.t("Loading..."));
    });

    this.listen(document, "turbo:fetch-request-error", (event) => {
      const frame = this.mainFrameFromEventTarget(event.target);
      if (!frame) return;

      this.failMainFrameRequest(frame);
    });

    this.listen(document, "turbo:before-fetch-response", (event) => {
      const frame = event.target;
      if (!this.isMainFrame(frame) || event.defaultPrevented) return;
      const response = (event as CustomEvent<TurboFetchResponseDetail>).detail?.fetchResponse;
      // Turbo cannot render non-HTML errors or emit frame-missing for them.
      // Form responses and HTML error pages retain their own handling.
      if (!response?.failed || response.isHTML) return;

      event.preventDefault();
      this.failMainFrameRequest(frame);
    });

    this.listen(document, "turbo:frame-missing", (event) => {
      const frame = event.target;
      if (!this.isMainFrame(frame)) return;

      const detail = (event as CustomEvent<TurboFrameMissingDetail>).detail;
      if (!detail?.response || typeof detail.visit !== "function") return;

      event.preventDefault();
      this.setMainFrameState("failed", frame);
      this.preloaderForMainFrame(frame).hide();
      void detail.visit(detail.response);
    });
  }

  private failMainFrameRequest(frame: HTMLElement): void {
    this.setMainFrameState("failed", frame);
    this.preloaderForMainFrame(frame).hide();
    this.showMainFrameRequestError();
  }

  private isMainFrame(target: EventTarget | null): target is HTMLElement {
    return target instanceof HTMLElement && target.matches(this.mainFrameSelector);
  }

  private mainFrameFromEventTarget(target: EventTarget | null): HTMLElement | null {
    if (!(target instanceof Element)) return null;
    return target.closest<HTMLElement>(this.mainFrameSelector);
  }

  private isRestorationFetch(event: Event): boolean {
    const detail = (event as CustomEvent<TurboFetchRequestDetail>).detail;
    return detail?.visit?.action === "restore";
  }

  private preloaderForMainFrame(frame: HTMLElement): ScopedPreloader {
    if (!this.mainFramePreloader || this.mainFramePreloader.root !== frame) {
      this.mainFramePreloader = this.createPreloader(frame);
    }

    return this.mainFramePreloader;
  }

  private setMainFrameState(state: MainFrameState, frame = this.root.querySelector<HTMLElement>(this.mainFrameSelector)): void {
    if (!frame) return;
    frame.dataset.omFrameState = state;
  }

  private hideMainFrameLoading(frame = this.root.querySelector<HTMLElement>(this.mainFrameSelector)): void {
    if (!frame) return;
    ScopedPreloader.clearWithin(frame);
    this.preloaderForMainFrame(frame).hide();
    this.setMainFrameState("mounted", frame);
  }

  private installInitialLoadingLifecycle(): void {
    this.listen(this.root, "om:component:render-complete", (event) => this.hideClosestInitialLoadingScope(event.target));
    this.listen(this.root, "om:component:render-error", (event) => this.hideClosestInitialLoadingScope(event.target));
  }

  private installDynamicContentLifecycle(): void {
    this.listen<CustomEvent<DynamicContentMountDetail>>(this.root, "om:component:before-dynamic-content-mount", (event) => {
      const detail = event.detail;
      const root = detail?.root ?? this.root;
      detail?.waitUntil?.(this.registerDeclarativeComponents(root));
    });
  }

  private showInitialLoadingScopes(root: ParentNode): void {
    for (const scope of queryAllSelfOrDescendants<HTMLElement>(root, this.initialLoadingSelector)) {
      this.preloaderForInitialLoadingScope(scope).show(this.i18n.t("Loading..."));
    }
  }

  private hideClosestInitialLoadingScope(target: EventTarget | null): void {
    if (!(target instanceof Element)) return;
    const scope = target.closest<HTMLElement>(this.initialLoadingSelector);
    if (!scope || !this.root.contains(scope)) return;
    this.hideInitialLoadingScope(scope);
  }

  private hideInitialLoadingScope(scope: HTMLElement): void {
    this.initialLoadingPreloaders.get(scope)?.hide();
    this.initialLoadingPreloaders.delete(scope);
  }

  private clearInitialLoadingScopes(root: ParentNode): void {
    for (const scope of Array.from(this.initialLoadingPreloaders.keys())) {
      if (root === scope || (root instanceof Element && root.contains(scope)) || (root instanceof Document && root.contains(scope))) {
        this.hideInitialLoadingScope(scope);
      }
    }
  }

  private preloaderForInitialLoadingScope(scope: HTMLElement): ScopedPreloader {
    let preloader = this.initialLoadingPreloaders.get(scope);
    if (!preloader) {
      preloader = this.createPreloader(scope);
      this.initialLoadingPreloaders.set(scope, preloader);
    }

    return preloader;
  }

  private async registerDeclarativeComponents(root: ParentNode = this.root): Promise<void> {
    const names = this.declarativeComponentNames(root);
    for (const name of names) {
      await this.registerComponentLoader(name);
    }
  }

  private async registerComponentLoader(name: string): Promise<void> {
    this.signal.throwIfAborted();
    const loader = this.componentLoaders[name];
    if (!loader) return;
    const component = await loader();
    this.signal.throwIfAborted();
    this.components.register(name, component);
  }

  private declarativeComponentNames(root: ParentNode = this.root): Set<string> {
    const names = new Set<string>();

    for (const element of queryAllSelfOrDescendants<HTMLElement>(root, "[data-om-component]")) {
      if (element.dataset.omComponent) names.add(element.dataset.omComponent);
    }

    return names;
  }

  private decorateScrollAreas(root: ParentNode = this.root): void {
    for (const element of queryAllSelfOrDescendants<HTMLElement>(root, "[data-simplebar]")) {
      if (element.dataset.omComponent) continue;
      element.dataset.omComponent = "scroll-area";
    }
  }

  private decorateLegacyDropdowns(root: ParentNode = this.root): void {
    for (const element of queryAllSelfOrDescendants<HTMLElement>(root, ".om-dropdown, [data-om-component='dropdown']")) {
      const toggle = element.querySelector<HTMLElement>("[data-om-dropdown-toggle]");
      const menu = element.querySelector<HTMLElement>(".om-dropdown-menu, [data-om-dropdown-menu]");
      if (!toggle || !menu) continue;

      element.dataset.omComponent = "dropdown";
      toggle.dataset.omDropdownToggle = "";
      menu.dataset.omDropdownMenu = "";

      if (!menu.classList.contains("show")) {
        menu.classList.add("hidden");
        menu.hidden = true;
      }
    }
  }
}

export function createOldmanApp(options: OldmanAppOptions = {}): BasePage {
  return new BasePage(options);
}
