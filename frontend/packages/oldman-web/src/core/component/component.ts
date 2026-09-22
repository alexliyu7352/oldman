import type { RunActionOptions } from "../actions/actions";
import type { ComponentManager } from "./manager";
import type { Page } from "../page/page";
import type { I18nRuntime } from "../i18n";
import { getOldmanContext } from "../runtime/context";
import { consoleLogger } from "../services/logger";
import { abortable } from "../services/abort";
import { ScopedRoot } from "../scope/scoped-root";
import type { ComponentState } from "./registry";

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

export abstract class Component extends ScopedRoot {
  readonly manager: ComponentManager | null;
  readonly page: Page | null;

  /**
   * 创建组件实例，并注入页面作用域服务与共享 i18n 运行时。
   */
  constructor(root: HTMLElement, options: ComponentOptions = {}) {
    const context = getOldmanContext();
    const page = options.page ?? null;
    super(root, {
      i18n: options.i18n ?? page?.i18n ?? context.i18n,
      logger: page?.logger ?? context.logger ?? consoleLogger,
      // 父页面被取消时，还卡在挂载钩子里的子组件也要停下。
      parentSignal: page?.signal ?? null,
      stateDatasetKey: "omComponentState",
      stateEventName: "om:component:state",
      stateSubjectKey: "component"
    });
    this.page = page;
    this.manager = options.manager ?? page?.components ?? null;
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

}

function createComponentLifecycleError(errors: unknown[]): unknown {
  if (errors.length === 1) {
    return errors[0];
  }

  return new AggregateError(errors, "Component unmount failed");
}
