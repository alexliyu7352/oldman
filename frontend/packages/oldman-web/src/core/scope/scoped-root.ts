import { runAction as runCoreAction, type RunActionOptions } from "../actions/actions";
import { queryAllSelfOrDescendants, querySelfOrDescendant } from "../dom/helpers";
import { onCoreEvent as listenCoreEvent, type CoreEventHandler, type CoreEventName } from "../events";
import type { HttpClient } from "../http/client";
import type { I18nRuntime } from "../i18n";
import { getOldmanContext } from "../runtime/context";
import {
  AssetService,
  type AssetBundleOptions,
  type AssetBundleResult,
  type AssetElement,
  type ScriptAssetOptions,
  type StylesheetAssetOptions
} from "../services/assets";
import { CleanupRegistry, type CleanupCallback } from "../services/cleanup";
import {
  EventService,
  type CustomEventTarget,
  type DelegatedEventHandler,
  type DirectEventHandler,
  type EmitEventOptions
} from "../services/events";
import type { Logger } from "../services/logger";
import { ScopedPreloader } from "../services/preloader";
import { TimerService } from "../services/timers";
import { TransitionService, type TransitionCallback, type TransitionName } from "../services/transitions";

/** 一个作用域从创建到卸载经历的状态。Page 和 Component 走的是同一条。 */
export type ScopeState = "created" | "mounting" | "mounted" | "unmounting" | "unmounted" | "failed";

export type ScopeRunActionOptions = Omit<RunActionOptions, "http" | "pageRegistry" | "root" | "transitions">;

export interface ScopedRootOptions {
  i18n: I18nRuntime;
  logger: Logger;
  /** 父作用域的信号；父被取消时子也要停下，哪怕它还卡在挂载钩子里。 */
  parentSignal?: AbortSignal | null;
  /** 状态镜像到根节点上的 dataset 键，例如 `omPageState`。 */
  stateDatasetKey: string;
  /** 状态变化时从根节点派发的事件名，例如 `om:page:state`。 */
  stateEventName: string;
  /** 状态事件里指代这个作用域自身的字段名，例如 `page`。 */
  stateSubjectKey: string;
}

/**
 * 绑定在一个根节点上、有生命周期、并拥有一组作用域服务的东西。
 *
 * Page 和 Component 曾经各自实现了这整套：同样的十二个服务、同样二十来个转发方法、
 * 同样的状态机。两份代码只在名字上不同，于是也就只在名字上保持同步——前一轮
 * "取消后仍然改写历史条目"的缺陷，正是从这条缝里长出来的。现在它们共用这一个基类，
 * 差异收敛成构造时传入的三个名字。
 */
export abstract class ScopedRoot {
  protected readonly cleanupRegistry = new CleanupRegistry();
  private readonly scopeController = new AbortController();
  private currentState: ScopeState = "created";
  private readonly stateDatasetKey: string;
  private readonly stateEventName: string;
  private readonly stateSubjectKey: string;
  readonly signal: AbortSignal = this.scopeController.signal;
  readonly events: EventService;
  readonly timers: TimerService;
  readonly assets: AssetService;
  readonly transitions: TransitionService = new TransitionService();
  readonly http: HttpClient;
  readonly i18n: I18nRuntime;
  readonly logger: Logger;
  readonly preloader: ScopedPreloader;

  /** 建立作用域服务，并把生命周期挂到父作用域的取消信号上。 */
  constructor(readonly root: HTMLElement, options: ScopedRootOptions) {
    this.i18n = options.i18n;
    this.logger = options.logger;
    this.stateDatasetKey = options.stateDatasetKey;
    this.stateEventName = options.stateEventName;
    this.stateSubjectKey = options.stateSubjectKey;

    const parentSignal = options.parentSignal ?? null;
    if (parentSignal?.aborted) this.scopeController.abort();
    else parentSignal?.addEventListener("abort", () => this.scopeController.abort(), {
      once: true,
      signal: this.signal
    });

    this.preloader = new ScopedPreloader(root, this.cleanupRegistry, this.i18n);
    this.cleanupRegistry.add(() => this.scopeController.abort());
    this.http = getOldmanContext().createHttpClient({ signal: this.signal });
    this.events = new EventService(root, this.cleanupRegistry);
    this.timers = new TimerService(this.cleanupRegistry);
    this.assets = new AssetService(this.cleanupRegistry);
  }

  /** 当前生命周期状态。 */
  get state(): ScopeState {
    return this.currentState;
  }

  /**
   * 更新状态，并从根节点派发状态变化事件。
   *
   * 进入 `unmounting` 时立刻 abort：在途的 UI 工作要在异步卸载钩子释放资源之前停下。
   * 也就是说卸载钩子本身看到的已经是一个 aborted 的信号——凡是在那里发请求的使用方，
   * 都必须把取消当成正常退出。
   */
  setState(state: ScopeState): void {
    if (this.currentState === state) return;

    const previousState = this.currentState;
    this.currentState = state;
    if (state === "unmounting") this.scopeController.abort();
    this.root.dataset[this.stateDatasetKey] = state;
    this.root.dispatchEvent(
      new CustomEvent(this.stateEventName, {
        bubbles: true,
        detail: { [this.stateSubjectKey]: this, previousState, state }
      })
    );
  }

  /** 注册作用域内的委托 DOM 事件监听器。 */
  on<K extends keyof HTMLElementEventMap>(
    eventName: K,
    selector: string,
    handler: DelegatedEventHandler<HTMLElementEventMap[K]>
  ): void {
    this.events.on(eventName, selector, handler);
  }

  /** 注册作用域内的委托自定义事件监听器。 */
  onCustom<TDetail = unknown>(
    eventName: string,
    selector: string,
    handler: DelegatedEventHandler<CustomEvent<TDetail>>
  ): void {
    this.events.onCustom(eventName, selector, handler);
  }

  /** 注册直接事件监听器，并在清理阶段自动移除。 */
  listen<TEvent extends Event = Event>(
    target: CustomEventTarget,
    eventName: string,
    handler: DirectEventHandler<TEvent>,
    options?: AddEventListenerOptions
  ): void {
    this.events.listen(target, eventName, handler, options);
  }

  /** 从根节点派发可冒泡的自定义事件。 */
  emit<TDetail = unknown>(eventName: string, detail?: TDetail, options: EmitEventOptions<TDetail> = {}): boolean {
    return this.events.emit(this.root, eventName, detail, options);
  }

  /** 注册 Oldman 核心事件监听器，并在清理阶段移除。 */
  onCoreEvent<TEventName extends CoreEventName>(
    eventName: TEventName,
    handler: CoreEventHandler<TEventName>,
    target: Document | HTMLElement = this.root
  ): void {
    this.cleanupRegistry.add(listenCoreEvent(target, eventName, handler));
  }

  /** 使用本作用域的 HTTP 与过渡服务执行 data action。 */
  runAction(trigger: HTMLElement, options: ScopeRunActionOptions = {}) {
    return runCoreAction(trigger, {
      ...options,
      root: this.root,
      http: this.http,
      pageRegistry: getOldmanContext().pageRegistry,
      transitions: this.transitions
    });
  }

  /** 加载样式表，并按配置注册到清理流程。 */
  loadStylesheet(href: string, options: StylesheetAssetOptions = {}): HTMLLinkElement {
    return this.assets.stylesheet(href, options);
  }

  /** 加载脚本，并按配置注册到清理流程。 */
  loadScript(src: string, options: ScriptAssetOptions = {}): Promise<HTMLScriptElement> {
    return this.assets.script(src, options);
  }

  /** 批量加载样式表和脚本。 */
  loadAssets(options: AssetBundleOptions): Promise<AssetBundleResult> {
    return this.assets.loadBundle(options);
  }

  /** 通过 id 或元素引用移除一个已加载资源。 */
  removeAsset(asset: string | AssetElement): boolean {
    return this.assets.remove(asset);
  }

  /** 移除一次资源包加载返回的全部资源。 */
  removeAssets(bundle: AssetBundleResult): void {
    this.assets.removeBundle(bundle);
  }

  /** 使用命名过渡显示元素。 */
  show(element: HTMLElement, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.show(element, transition);
  }

  /** 使用命名过渡隐藏元素。 */
  hide(element: HTMLElement, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.hide(element, transition);
  }

  /** 使用命名过渡切换元素可见性。 */
  toggle(element: HTMLElement, visible?: boolean, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.toggle(element, visible, transition);
  }

  /**
   * 在回调执行期间追加 class，回调结束（含抛异常）后移除。
   *
   * 注册一条兜底、并在回调 settle 后立刻注销。两半都必要：
   * `TransitionService.withClasses` 的 `finally` 覆盖正常和异常路径，但覆盖不了
   * **回调永远不 settle** 的情况，那时卸载时的兜底是唯一会把 class 摘掉的东西；
   * 而只注册不注销，每调用一次就永久多留一个持有 `element` 的闭包——一个每次点击都加
   * `busy` 类的按钮，点一次积一个，节点早已离开文档也回收不掉。
   */
  withClasses<T>(element: Element, classNames: string[], callback: TransitionCallback<T>): Promise<T> {
    const undo = this.cleanupRegistry.add(() => element.classList.remove(...classNames));
    return this.transitions
      .withClasses(element, classNames, callback)
      .finally(() => this.cleanupRegistry.remove(undo));
  }

  /** 切换元素上的 class，并返回最终启用状态。 */
  toggleClass(element: Element, className: string, force?: boolean): boolean {
    return this.transitions.toggleClass(element, className, force);
  }

  /** 注册清理回调，执行顺序与注册顺序相反。 */
  cleanup(callback: CleanupCallback): void {
    this.cleanupRegistry.add(callback);
  }

  /** 在根节点内查找一个元素，缺失时抛出错误。 */
  $<TElement extends HTMLElement = HTMLElement>(selector: string): TElement {
    const element = querySelfOrDescendant<TElement>(this.root, selector);
    if (!element) throw new Error(`Element not found: ${selector}`);
    return element;
  }

  /** 查找根节点内所有匹配元素，包含根节点自身。 */
  $$<TElement extends HTMLElement = HTMLElement>(selector: string): TElement[] {
    return queryAllSelfOrDescendants<TElement>(this.root, selector);
  }

  /** 运行已注册清理回调，并等待异步清理完成。 */
  runCleanup(): Promise<void> {
    return this.cleanupRegistry.run(this.logger);
  }
}
