import { Component } from "../core/component/component";
import { goBackOrFallback, HISTORY_BACK_SELECTOR } from "../core/runtime/history-back";

/**
 * 标准历史返回行为：优先走 Turbo 历史，缺少历史时才使用声明的 fallback。
 * 运行时在 document 上还有一条同样的兜底监听，覆盖页面尚未挂载完的那段时间。
 */
export class HistoryBack extends Component {
  static readonly componentName = "history-back";

  override async mount(): Promise<void> {
    this.on("click", HISTORY_BACK_SELECTOR, (event, matchedElement) => {
      event.preventDefault();
      goBackOrFallback(matchedElement as HTMLElement, (url) => this.navigateToFallback(url));
    });
  }

  protected navigateToFallback(url: string): void {
    window.location.assign(url);
  }
}
