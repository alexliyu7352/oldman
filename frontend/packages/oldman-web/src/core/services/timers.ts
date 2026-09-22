import type { CleanupRegistry } from "./cleanup";

/** 作用域内的定时器：卸载时统一清掉。 */
export class TimerService {
  constructor(private readonly cleanup: CleanupRegistry) {}

  /**
   * 一次性定时器：触发后立刻注销它的清理登记。
   *
   * 不注销的话，一个每秒重排一次的定时器在长驻页面上会不停往注册表里压闭包——
   * 只增不减，直到作用域卸载。触发之后 `clearTimeout` 已无事可做，留着只是占内存。
   */
  timeout(callback: () => void, delay: number): number {
    let id = 0;
    const undo = this.cleanup.add(() => window.clearTimeout(id));
    id = window.setTimeout(() => {
      this.cleanup.remove(undo);
      callback();
    }, delay);
    return id;
  }

  /**
   * 周期定时器：一直到作用域卸载才清，所以它的登记必须留着。
   *
   * 需要提前停掉时自己拿 `clearInterval` 清，那之后这条登记就只是一次无害的重复调用。
   */
  interval(callback: () => void, delay: number): number {
    const id = window.setInterval(callback, delay);
    this.cleanup.add(() => window.clearInterval(id));
    return id;
  }
}
