import { CleanupRegistry, type CleanupCallback } from "../services/cleanup";
import {
  EventService,
  type CustomEventTarget,
  type DelegatedEventHandler,
  type DirectEventHandler,
  type EmitEventOptions
} from "../services/events";
import { consoleLogger, type Logger } from "../services/logger";
import { TimerService } from "../services/timers";
import {
  AssetService,
  type AssetBundleOptions,
  type AssetBundleResult,
  type AssetElement,
  type ScriptAssetOptions,
  type StylesheetAssetOptions
} from "../services/assets";
import { TransitionService, type TransitionCallback, type TransitionName } from "../services/transitions";
import { createPreferenceStore, type PreferenceStore } from "../services/preferences";
import { ScopedPreloader } from "../services/preloader";
import type { HttpClient } from "../http/client";
import type { I18nRuntime } from "../i18n";
import { queryAllSelfOrDescendants, querySelfOrDescendant } from "../dom/helpers";
import { onCoreEvent as listenCoreEvent, type CoreEventHandler, type CoreEventName } from "../events";
import { runAction as runCoreAction, type RunActionOptions } from "../actions/actions";
import { ComponentManager } from "../component/manager";
import { ComponentRegistry } from "../component/registry";
import { getOldmanContext } from "../runtime/context";
import {
  ResponseActionRunner,
  type ResponseAction,
  type ResponseActionContext,
  type ResponseFeedback
} from "../actions/response-actions";

export interface PageConstructor<TPage extends Page = Page> {
  new (root: HTMLElement): TPage;
}

export interface NamedPageConstructor<TPage extends Page = Page> extends PageConstructor<TPage> {
  readonly pageName: string;
}

export type PageState = "created" | "mounting" | "mounted" | "unmounting" | "unmounted" | "failed";

export interface PageStateChangeDetail<TPage extends Page = Page> {
  page: TPage;
  previousState: PageState;
  state: PageState;
}

export type PageRunActionOptions = Omit<RunActionOptions, "http" | "pageRegistry" | "root" | "transitions">;

export abstract class Page {
  protected readonly cleanupRegistry = new CleanupRegistry();
  private readonly pageController = new AbortController();
  private currentState: PageState = "created";
  readonly signal: AbortSignal = this.pageController.signal;
  readonly events: EventService;
  readonly timers: TimerService;
  readonly assets: AssetService;
  readonly transitions: TransitionService = new TransitionService();
  readonly preferences: PreferenceStore = createPreferenceStore();
  readonly http: HttpClient;
  readonly i18n: I18nRuntime;
  readonly logger: Logger;
  readonly preloader: ScopedPreloader;
  /**
   * 页面作用域组件管理器，用于注册和挂载当前页面根节点内的私有组件。
   */
  readonly components: ComponentManager;
  readonly responseActions: ResponseActionRunner;
  feedback: ResponseFeedback | null = null;

  /**
   * 创建页面实例，并初始化页面作用域服务和共享 i18n 运行时。
   */
  constructor(readonly root: HTMLElement, readonly mainFrameSelector: string = "#oldman-main") {
    const context = getOldmanContext();
    this.i18n = context.i18n;
    this.logger = context.logger ?? consoleLogger;
    this.preloader = new ScopedPreloader(root, this.cleanupRegistry, this.i18n);
    this.cleanupRegistry.add(() => this.pageController.abort());
    this.components = new ComponentManager({
      page: this,
      registry: new ComponentRegistry(context.componentRegistry)
    });
    this.responseActions = new ResponseActionRunner(this);
    this.http = context.createHttpClient({ signal: this.signal });
    this.events = new EventService(root, this.cleanupRegistry);
    this.timers = new TimerService(this.cleanupRegistry);
    this.assets = new AssetService(this.cleanupRegistry);
  }

  get state(): PageState {
    return this.currentState;
  }

  async beforeMount(): Promise<void> {}
  async mount(): Promise<void> {}
  async afterMount(): Promise<void> {}
  async beforeUnmount(): Promise<void> {}
  async unmount(): Promise<void> {}

  async handleResponseAction(
    _action: ResponseAction,
    _context: ResponseActionContext
  ): Promise<boolean> {
    return false;
  }

  on<K extends keyof HTMLElementEventMap>(
    eventName: K,
    selector: string,
    handler: DelegatedEventHandler<HTMLElementEventMap[K]>
  ): void {
    this.events.on(eventName, selector, handler);
  }

  onCustom<TDetail = unknown>(
    eventName: string,
    selector: string,
    handler: DelegatedEventHandler<CustomEvent<TDetail>>
  ): void {
    this.events.onCustom(eventName, selector, handler);
  }

  listen<TEvent extends Event = Event>(
    target: CustomEventTarget,
    eventName: string,
    handler: DirectEventHandler<TEvent>,
    options?: AddEventListenerOptions
  ): void {
    this.events.listen(target, eventName, handler, options);
  }

  emit<TDetail = unknown>(
    eventName: string,
    detail?: TDetail,
    options: EmitEventOptions<TDetail> = {}
  ): boolean {
    return this.events.emit(this.root, eventName, detail, options);
  }

  onCoreEvent<TEventName extends CoreEventName>(
    eventName: TEventName,
    handler: CoreEventHandler<TEventName>,
    target: Document | HTMLElement = this.root
  ): void {
    this.cleanupRegistry.add(listenCoreEvent(target, eventName, handler));
  }

  runAction(trigger: HTMLElement, options: PageRunActionOptions = {}) {
    return runCoreAction(trigger, {
      ...options,
      root: this.root,
      http: this.http,
      pageRegistry: getOldmanContext().pageRegistry,
      transitions: this.transitions
    });
  }

  createPreloader(root: HTMLElement): ScopedPreloader {
    return new ScopedPreloader(root, this.cleanupRegistry, this.i18n);
  }

  loadStylesheet(href: string, options: StylesheetAssetOptions = {}): HTMLLinkElement {
    return this.assets.stylesheet(href, options);
  }

  loadScript(src: string, options: ScriptAssetOptions = {}): Promise<HTMLScriptElement> {
    return this.assets.script(src, options);
  }

  loadAssets(options: AssetBundleOptions): Promise<AssetBundleResult> {
    return this.assets.loadBundle(options);
  }

  removeAsset(asset: string | AssetElement): boolean {
    return this.assets.remove(asset);
  }

  removeAssets(bundle: AssetBundleResult): void {
    this.assets.removeBundle(bundle);
  }

  show(element: HTMLElement, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.show(element, transition);
  }

  hide(element: HTMLElement, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.hide(element, transition);
  }

  toggle(element: HTMLElement, visible?: boolean, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.toggle(element, visible, transition);
  }

  withClasses<T>(element: Element, classNames: string[], callback: TransitionCallback<T>): Promise<T> {
    this.cleanup(() => element.classList.remove(...classNames));
    return this.transitions.withClasses(element, classNames, callback);
  }

  toggleClass(element: Element, className: string, force?: boolean): boolean {
    return this.transitions.toggleClass(element, className, force);
  }

  cleanup(callback: CleanupCallback): void {
    this.cleanupRegistry.add(callback);
  }

  $<TElement extends HTMLElement = HTMLElement>(selector: string): TElement {
    const element = querySelfOrDescendant<TElement>(this.root, selector);
    if (!element) throw new Error(`Element not found: ${selector}`);
    return element;
  }

  $$<TElement extends HTMLElement = HTMLElement>(selector: string): TElement[] {
    return queryAllSelfOrDescendants<TElement>(this.root, selector);
  }

  runCleanup(): Promise<void> {
    return this.cleanupRegistry.run(this.logger);
  }

  unmountComponents(): Promise<void> {
    return this.components.unmount(this.root);
  }

  setState(state: PageState): void {
    if (this.currentState === state) return;

    const previousState = this.currentState;
    this.currentState = state;
    // Stop in-flight UI work before asynchronous unmount hooks release resources.
    if (state === "unmounting") this.pageController.abort();
    this.root.dataset.omPageState = state;
    this.root.dispatchEvent(
      new CustomEvent<PageStateChangeDetail>("om:page:state", {
        bubbles: true,
        detail: {
          page: this,
          previousState,
          state
        }
      })
    );
  }
}
