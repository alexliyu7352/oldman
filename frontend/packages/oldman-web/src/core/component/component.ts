import { runAction as runCoreAction, type RunActionOptions } from "../actions/actions";
import { queryAllSelfOrDescendants, querySelfOrDescendant } from "../dom/helpers";
import { onCoreEvent as listenCoreEvent, type CoreEventHandler, type CoreEventName } from "../events";
import type { Page } from "../page/page";
import type { ComponentManager } from "./manager";
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
import type { HttpClient } from "../http/client";
import type { I18nRuntime } from "../i18n";
import { getOldmanContext } from "../runtime/context";
import { consoleLogger, type Logger } from "../services/logger";
import { ScopedPreloader } from "../services/preloader";
import { TimerService } from "../services/timers";
import { TransitionService, type TransitionCallback, type TransitionName } from "../services/transitions";
import type { ComponentState } from "./registry";
import { abortable } from "../services/abort";

export interface ComponentOptions {
  i18n?: I18nRuntime;
  manager?: ComponentManager | null;
  page?: Page | null;
}

export interface ComponentStateChangeDetail<TComponent extends Component = Component> {
  component: TComponent;
  previousState: ComponentState;
  state: ComponentState;
}

export type ComponentRunActionOptions = Omit<RunActionOptions, "http" | "pageRegistry" | "root" | "transitions">;

export abstract class Component {
  protected readonly cleanupRegistry = new CleanupRegistry();
  private readonly componentController = new AbortController();
  private currentState: ComponentState = "created";
  readonly signal: AbortSignal = this.componentController.signal;
  readonly events: EventService;
  readonly timers: TimerService;
  readonly assets: AssetService;
  readonly transitions: TransitionService = new TransitionService();
  readonly http: HttpClient;
  readonly i18n: I18nRuntime;
  readonly logger: Logger;
  readonly manager: ComponentManager | null;
  readonly page: Page | null;
  readonly preloader: ScopedPreloader;

  /**
   * 创建组件实例，并注入页面作用域服务与共享 i18n 运行时。
   */
  constructor(readonly root: HTMLElement, options: ComponentOptions = {}) {
    const context = getOldmanContext();
    this.page = options.page ?? null;
    // Parent cancellation also stops a child still awaiting its mount hook.
    if (this.page?.signal.aborted) this.componentController.abort();
    else this.page?.signal.addEventListener("abort", () => this.componentController.abort(), {
      once: true,
      signal: this.signal
    });
    this.manager = options.manager ?? options.page?.components ?? null;
    this.i18n =
      options.i18n ??
      options.page?.i18n ??
      context.i18n;
    this.logger = options.page?.logger ?? context.logger ?? consoleLogger;
    this.preloader = new ScopedPreloader(root, this.cleanupRegistry, this.i18n);
    this.cleanupRegistry.add(() => this.componentController.abort());
    this.http = context.createHttpClient({ signal: this.signal });
    this.events = new EventService(root, this.cleanupRegistry);
    this.timers = new TimerService(this.cleanupRegistry);
    this.assets = new AssetService(this.cleanupRegistry);
  }

  /**
   * 返回组件当前生命周期状态。
   */
  get state(): ComponentState {
    return this.currentState;
  }

  /**
   * 在组件主要挂载逻辑开始前执行。
   */
  async beforeMount(): Promise<void> {}

  /**
   * 将组件连接到根节点，并注册运行时行为。
   */
  async mount(): Promise<void> {}

  /**
   * 在组件完成挂载并进入 DOM 可用阶段后执行。
   */
  async afterMount(): Promise<void> {}

  /**
   * 在组件开始卸载前立即执行。
   */
  async beforeUnmount(): Promise<void> {}

  /**
   * 在注册的清理回调运行前断开组件行为。
   */
  async unmount(): Promise<void> {}

  /**
   * 返回渲染驱动组件可选使用的模板内容。
   */
  template(): string | Node | Node[] | void {}

  /**
   * 当模板存在时，将模板输出写入组件根节点。
   */
  async render(): Promise<void> {
    const output = this.template();
    if (output === undefined) return;

    if (typeof output === "string") {
      this.root.innerHTML = output;
      return;
    }

    if (Array.isArray(output)) {
      this.root.replaceChildren(...output);
      return;
    }

    this.root.replaceChildren(output);
  }

  /**
   * 启动组件生命周期，并在成功后标记为已挂载。
   */
  async start(): Promise<void> {
    try {
      this.signal.throwIfAborted();
      this.setState("mounting");
      await abortable(this.beforeMount(), this.signal);
      this.signal.throwIfAborted();
      await abortable(this.render(), this.signal);
      this.signal.throwIfAborted();
      await abortable(this.mount(), this.signal);
      this.signal.throwIfAborted();
      await abortable(this.afterMount(), this.signal);
      this.signal.throwIfAborted();
      this.setState("mounted");
    } catch (error) {
      // The owner stopping this instance performs cleanup; do not resurrect it as failed.
      if (this.signal.aborted) throw error;
      this.setState("failed");
      try {
        await this.runCleanup();
      } catch {
        // 清理失败不应覆盖原始挂载错误。
      }
      throw error;
    }
  }

  /**
   * 停止组件生命周期，执行异步清理，并标记为已卸载。
   */
  async stop(): Promise<void> {
    const errors: unknown[] = [];
    this.setState("unmounting");

    try {
      await this.beforeUnmount();
    } catch (error) {
      errors.push(error);
    }

    try {
      await this.unmount();
    } catch (error) {
      errors.push(error);
    }

    try {
      await this.runCleanup();
    } catch (error) {
      errors.push(error);
    }

    if (errors.length > 0) {
      this.setState("failed");
      throw createComponentLifecycleError(errors);
    }

    this.setState("unmounted");
  }

  /**
   * 注册作用域限定在组件根节点内的委托 DOM 事件监听器。
   */
  on<K extends keyof HTMLElementEventMap>(
    eventName: K,
    selector: string,
    handler: DelegatedEventHandler<HTMLElementEventMap[K]>
  ): void {
    this.events.on(eventName, selector, handler);
  }

  /**
   * 注册作用域限定在组件根节点内的委托自定义事件监听器。
   */
  onCustom<TDetail = unknown>(
    eventName: string,
    selector: string,
    handler: DelegatedEventHandler<CustomEvent<TDetail>>
  ): void {
    this.events.onCustom(eventName, selector, handler);
  }

  /**
   * 注册直接事件监听器，并在清理阶段自动移除。
   */
  listen<TEvent extends Event = Event>(
    target: CustomEventTarget,
    eventName: string,
    handler: DirectEventHandler<TEvent>,
    options?: AddEventListenerOptions
  ): void {
    this.events.listen(target, eventName, handler, options);
  }

  /**
   * 从组件根节点派发可冒泡的自定义事件。
   */
  emit<TDetail = unknown>(eventName: string, detail?: TDetail, options: EmitEventOptions<TDetail> = {}): boolean {
    return this.events.emit(this.root, eventName, detail, options);
  }

  /**
   * 注册 Oldman 核心事件监听器，并在清理阶段移除。
   */
  onCoreEvent<TEventName extends CoreEventName>(
    eventName: TEventName,
    handler: CoreEventHandler<TEventName>,
    target: Document | HTMLElement = this.root
  ): void {
    this.cleanupRegistry.add(listenCoreEvent(target, eventName, handler));
  }

  /**
   * 使用组件作用域的 HTTP 与过渡服务执行 data action。
   */
  runAction(trigger: HTMLElement, options: ComponentRunActionOptions = {}) {
    return runCoreAction(trigger, {
      ...options,
      root: this.root,
      http: this.http,
      pageRegistry: getOldmanContext().pageRegistry,
      transitions: this.transitions
    });
  }

  /**
   * 加载样式表，并按配置注册到组件清理流程。
   */
  loadStylesheet(href: string, options: StylesheetAssetOptions = {}): HTMLLinkElement {
    return this.assets.stylesheet(href, options);
  }

  /**
   * 加载脚本，并按配置注册到组件清理流程。
   */
  loadScript(src: string, options: ScriptAssetOptions = {}): Promise<HTMLScriptElement> {
    return this.assets.script(src, options);
  }

  /**
   * 通过组件资源服务批量加载样式表和脚本。
   */
  loadAssets(options: AssetBundleOptions): Promise<AssetBundleResult> {
    return this.assets.loadBundle(options);
  }

  /**
   * 通过 id 或元素引用移除一个已加载资源。
   */
  removeAsset(asset: string | AssetElement): boolean {
    return this.assets.remove(asset);
  }

  /**
   * 移除一次资源包加载返回的全部资源。
   */
  removeAssets(bundle: AssetBundleResult): void {
    this.assets.removeBundle(bundle);
  }

  /**
   * 使用命名过渡显示元素。
   */
  show(element: HTMLElement, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.show(element, transition);
  }

  /**
   * 使用命名过渡隐藏元素。
   */
  hide(element: HTMLElement, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.hide(element, transition);
  }

  /**
   * 使用命名过渡切换元素可见性。
   */
  toggle(element: HTMLElement, visible?: boolean, transition: TransitionName = "fade"): Promise<void> {
    return this.transitions.toggle(element, visible, transition);
  }

  /**
   * 在回调执行期间追加 class，并在清理阶段兜底移除。
   */
  withClasses<T>(element: Element, classNames: string[], callback: TransitionCallback<T>): Promise<T> {
    this.cleanup(() => element.classList.remove(...classNames));
    return this.transitions.withClasses(element, classNames, callback);
  }

  /**
   * 切换元素上的 class，并返回最终启用状态。
   */
  toggleClass(element: Element, className: string, force?: boolean): boolean {
    return this.transitions.toggleClass(element, className, force);
  }

  /**
   * 注册组件清理回调，执行顺序与注册顺序相反。
   */
  cleanup(callback: CleanupCallback): void {
    this.cleanupRegistry.add(callback);
  }

  /**
   * 在组件根节点内查找一个元素，缺失时抛出错误。
   */
  $<TElement extends HTMLElement = HTMLElement>(selector: string): TElement {
    const element = querySelfOrDescendant<TElement>(this.root, selector);
    if (!element) throw new Error(`Element not found: ${selector}`);
    return element;
  }

  /**
   * 查找组件根节点内所有匹配元素，包含根节点自身。
   */
  $$<TElement extends HTMLElement = HTMLElement>(selector: string): TElement[] {
    return queryAllSelfOrDescendants<TElement>(this.root, selector);
  }

  /**
   * 运行已注册清理回调，并等待异步清理完成。
   */
  runCleanup(): Promise<void> {
    return this.cleanupRegistry.run(this.logger);
  }

  /**
   * 更新组件状态，并从根节点派发状态变化事件。
   */
  setState(state: ComponentState): void {
    if (this.currentState === state) return;

    const previousState = this.currentState;
    this.currentState = state;
    if (state === "unmounting") this.componentController.abort();
    this.root.dataset.omComponentState = state;
    this.root.dispatchEvent(
      new CustomEvent<ComponentStateChangeDetail>("om:component:state", {
        bubbles: true,
        detail: {
          component: this,
          previousState,
          state
        }
      })
    );
  }
}

function createComponentLifecycleError(errors: unknown[]): unknown {
  if (errors.length === 1) {
    return errors[0];
  }

  return new AggregateError(errors, "Component unmount failed");
}
