import type { Logger } from "./logger";
import { consoleLogger } from "./logger";

export type CleanupCallback = () => void | Promise<void>;

export class CleanupRegistry {
  private callbacks: CleanupCallback[] = [];
  private completed = false;

  /**
   * 追加一条清理回调；返回值就是传入的回调本身，可以直接交给 `remove()` 注销。
   *
   * **会重复发生的注册必须配对注销**：注册表本身只是一个数组，不去重。在每次交互、每个
   * 请求上 `add()` 而不 `remove()`，就会不断累积闭包（闭包通常还持有 DOM 节点），
   * 直到作用域卸载才一起释放。
   */
  add(callback: CleanupCallback): CleanupCallback {
    if (this.completed) {
      throw new Error("Cannot add cleanup callback after registry has run");
    }

    this.callbacks.push(callback);
    return callback;
  }

  /**
   * 注销一条还没执行的清理回调。
   *
   * 给"注册一条兜底、事情正常完成后就不需要了"的场景用：`ScopedRoot.withClasses` 注册
   * "把 class 摘掉"，回调 settle 后立刻注销。没有它，那条兜底就只能永久留在注册表里——
   * 而它又不能不注册：回调**永远不 settle** 时，transitions 的 `finally` 不会执行，
   * 卸载时的这条兜底是唯一会把 class 摘掉的东西。
   */
  remove(callback: CleanupCallback): void {
    const index = this.callbacks.indexOf(callback);
    if (index >= 0) this.callbacks.splice(index, 1);
  }

  async run(logger: Logger = consoleLogger): Promise<void> {
    if (this.completed) return;
    this.completed = true;

    const callbacks = [...this.callbacks].reverse();
    this.callbacks = [];

    for (const callback of callbacks) {
      try {
        await callback();
      } catch (error) {
        logger.error("[oldman] cleanup callback failed", error);
      }
    }
  }
}
