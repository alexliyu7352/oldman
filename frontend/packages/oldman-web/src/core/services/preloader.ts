import type { I18nRuntime } from "../i18n";
import type { CleanupRegistry } from "./cleanup";

export type ScopedPreloaderStatus = "idle" | "loading";

export interface ScopedPreloaderOptions {
  message?: string;
}

export interface ScopedPreloaderEventDetail {
  message?: string;
}

const PRELOADER_SELECTOR = "[data-om-scoped-preloader]";
const PRELOADER_LABEL_SELECTOR = "[data-om-scoped-preloader-label]";
const PRELOADER_STATUS_SELECTOR = "[data-om-preloader-status]";

export class ScopedPreloader {
  private overlay: HTMLElement | null = null;

  static clearWithin(root: ParentNode): void {
    root.querySelectorAll<HTMLElement>(PRELOADER_SELECTOR).forEach((overlay) => overlay.remove());
    if (root instanceof HTMLElement && root.hasAttribute("data-om-preloader-status")) {
      root.dataset.omPreloaderStatus = "idle";
    }
    root.querySelectorAll<HTMLElement>(PRELOADER_STATUS_SELECTOR).forEach((element) => {
      element.dataset.omPreloaderStatus = "idle";
    });
  }

  constructor(
    readonly root: HTMLElement,
    cleanupRegistry: CleanupRegistry,
    private readonly i18n: I18nRuntime
  ) {
    this.root.dataset.omPreloaderStatus = "idle";
    this.root.addEventListener("om:preloader:show", this.handleShow);
    this.root.addEventListener("om:preloader:hide", this.handleHide);
    cleanupRegistry.add(() => {
      this.root.removeEventListener("om:preloader:show", this.handleShow);
      this.root.removeEventListener("om:preloader:hide", this.handleHide);
      this.hide();
    });
  }

  show(message = this.i18n.t("Loading...")): void {
    this.ensureScope();
    this.root.dataset.omPreloaderStatus = "loading";
    const overlay = this.ensureOverlay();
    overlay.hidden = false;
    overlay.setAttribute("aria-hidden", "false");
    overlay.querySelector<HTMLElement>(PRELOADER_LABEL_SELECTOR)!.textContent = message;
  }

  hide(): void {
    this.root.dataset.omPreloaderStatus = "idle";
    this.overlay?.remove();
    this.root.querySelector<HTMLElement>(`:scope > ${PRELOADER_SELECTOR}`)?.remove();
    this.overlay = null;
  }

  async withLoading<T>(task: () => Promise<T>, options: ScopedPreloaderOptions = {}): Promise<T> {
    this.show(options.message);
    try {
      return await task();
    } finally {
      this.hide();
    }
  }

  private ensureScope(): void {
    if (this.root.style.position) return;
    this.root.dataset.omPreloaderPositioned = "true";
  }

  private ensureOverlay(): HTMLElement {
    // 只认直接子级，和 `hide()` 的范围一致。用任意深度查找会捞到**内层作用域**的遮罩：
    // `ScopedRoot` 在构造函数里给每个 Page 和每个 Component 都建一个 ScopedPreloader，
    // 所以"外层里嵌着内层"是常态。接管之后外层的 hide() 会把内层的遮罩删掉，
    // 而内层的 data-om-preloader-status 还停在 loading——它认为自己在加载，却什么都没有。
    const existing = this.root.querySelector<HTMLElement>(`:scope > ${PRELOADER_SELECTOR}`);
    if (existing) {
      this.overlay = existing;
      return existing;
    }

    const overlay = document.createElement("div");
    overlay.dataset.omScopedPreloader = "";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    overlay.innerHTML = `
      <div data-om-scoped-preloader-spinner></div>
      <span data-om-scoped-preloader-label></span>
    `;
    this.root.append(overlay);
    this.overlay = overlay;
    return overlay;
  }

  private readonly handleShow = (event: Event): void => {
    const detail = (event as CustomEvent<ScopedPreloaderEventDetail>).detail;
    this.show(detail?.message);
  };

  private readonly handleHide = (): void => {
    this.hide();
  };
}
