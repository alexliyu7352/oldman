import { isSafeLink } from "../http/urls";

export const HISTORY_BACK_SELECTOR = "[data-om-history-back]";

type TurboHistoryState = {
  turbo?: {
    restorationIndex?: number;
  };
};

/** 只有 Turbo 推入过的历史条目才能安全后退，否则只能走声明的 fallback。 */
function canUseTurboHistory(): boolean {
  const state = window.history.state as TurboHistoryState | null;
  const index = state?.turbo?.restorationIndex;
  return typeof index === "number" && index > 0;
}

/**
 * 标准历史返回行为：优先走 Turbo 历史，缺少历史时才使用声明的 fallback。
 *
 * `navigate` 的实现是 `window.location.assign`，而它会执行 `javascript:` 地址，
 * 所以模板写下的 fallback 要先过 `isSafeLink`。拒绝时发一条 warn 而不是静默不动：
 * 写错 fallback 的是开发者，让他看见比让按钮神秘失灵好。
 */
export function goBackOrFallback(trigger: HTMLElement, navigate: (url: string) => void): void {
  if (canUseTurboHistory()) {
    window.history.back();
    return;
  }

  const fallback = trigger.dataset.omHistoryFallback;
  if (!fallback) return;
  if (!isSafeLink(fallback)) {
    console.warn(`Oldman ignored a data-om-history-fallback whose scheme executes: ${fallback}`);
    return;
  }

  navigate(fallback);
}

/**
 * 在 document 上补一条同样的委托监听。页面级组件只在挂载期间生效，而 Turbo 每次渲染
 * 都会重建页面：表单刚画出来、外壳还没挂载完的那一小段时间里，Cancel 会退化成一次普通
 * 跳转，用户回到的是一张丢了筛选、排序和页码的默认表格。已挂载的组件先 preventDefault，
 * 这里看到 defaultPrevented 就不再重复处理。
 */
export function startHistoryBack(target: Document = document): () => void {
  const handler = (event: MouseEvent): void => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const trigger = (event.target as Element | null)?.closest?.(HISTORY_BACK_SELECTOR);
    if (!(trigger instanceof HTMLElement)) return;

    event.preventDefault();
    goBackOrFallback(trigger, (url) => window.location.assign(url));
  };

  target.addEventListener("click", handler);
  return () => target.removeEventListener("click", handler);
}
