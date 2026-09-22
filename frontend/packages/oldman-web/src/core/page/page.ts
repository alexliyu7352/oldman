import type { RunActionOptions } from "../actions/actions";
import {
  ResponseActionRunner,
  type ResponseAction,
  type ResponseActionContext,
  type ResponseFeedback
} from "../actions/response-actions";
import { ComponentManager } from "../component/manager";
import { ComponentRegistry } from "../component/registry";
import { getOldmanContext } from "../runtime/context";
import { ScopedRoot, type ScopeState } from "../scope/scoped-root";
import { consoleLogger } from "../services/logger";
import { createPreferenceStore, type PreferenceStore } from "../services/preferences";
import { ScopedPreloader } from "../services/preloader";

export interface PageConstructor<TPage extends Page = Page> {
  new (root: HTMLElement): TPage;
}

export interface NamedPageConstructor<TPage extends Page = Page> extends PageConstructor<TPage> {
  readonly pageName: string;
}

export type PageState = ScopeState;

export interface PageStateChangeDetail<TPage extends Page = Page> {
  page: TPage;
  previousState: PageState;
  state: PageState;
}

export type PageRunActionOptions = Omit<RunActionOptions, "http" | "pageRegistry" | "root" | "transitions">;

export abstract class Page extends ScopedRoot {
  readonly preferences: PreferenceStore = createPreferenceStore();
  /**
   * 页面作用域组件管理器，用于注册和挂载当前页面根节点内的私有组件。
   */
  readonly components: ComponentManager;
  readonly responseActions: ResponseActionRunner;
  feedback: ResponseFeedback | null = null;

  /**
   * 创建页面实例，并初始化页面作用域服务和共享 i18n 运行时。
   */
  constructor(root: HTMLElement, readonly mainFrameSelector: string = "#oldman-main") {
    const context = getOldmanContext();
    super(root, {
      i18n: context.i18n,
      logger: context.logger ?? consoleLogger,
      stateDatasetKey: "omPageState",
      stateEventName: "om:page:state",
      stateSubjectKey: "page"
    });
    this.components = new ComponentManager({
      page: this,
      registry: new ComponentRegistry(context.componentRegistry)
    });
    this.responseActions = new ResponseActionRunner(this);
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

  createPreloader(root: HTMLElement): ScopedPreloader {
    return new ScopedPreloader(root, this.cleanupRegistry, this.i18n);
  }

  unmountComponents(): Promise<void> {
    return this.components.unmount(this.root);
  }
}
