import { Component } from "../core/component/component";

const HISTORY_BACK_SELECTOR = "[data-om-history-back]";

type TurboHistoryState = {
  turbo?: {
    restorationIndex?: number;
  };
};

/**
 * 标准历史返回行为：优先走 Turbo 历史，缺少历史时才使用声明的 fallback。
 */
export class HistoryBack extends Component {
  static readonly componentName = "history-back";

  override async mount(): Promise<void> {
    this.on("click", HISTORY_BACK_SELECTOR, (event, matchedElement) => {
      event.preventDefault();
      this.goBackOrFallback(matchedElement as HTMLElement);
    });
  }

  private goBackOrFallback(trigger: HTMLElement): void {
    if (this.canUseTurboHistory()) {
      window.history.back();
      return;
    }

    const fallback = trigger.dataset.omHistoryFallback;
    if (fallback) {
      this.navigateToFallback(fallback);
    }
  }

  private canUseTurboHistory(): boolean {
    const state = window.history.state as TurboHistoryState | null;
    const index = state?.turbo?.restorationIndex;
    return typeof index === "number" && index > 0;
  }

  protected navigateToFallback(url: string): void {
    window.location.assign(url);
  }
}
