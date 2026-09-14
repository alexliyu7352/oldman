import { Component } from "../core/component/component";

type PreloaderStatus = "idle" | "loading";

const MAIN_FRAME_SELECTOR = "turbo-frame#oldman-main";

/**
 * 页面级加载遮罩，接管 preloader DOM，并跟随 Turbo 生命周期显示/隐藏。
 */
export class Preloader extends Component {
  static readonly componentName = "preloader";

  override async mount(): Promise<void> {
    this.enablePreloaderMode();
    this.listen(document, "turbo:before-visit", () => this.showPreloader());
    this.listen(document, "turbo:before-fetch-request", (event) => {
      if (!this.isMainFrameEvent(event)) this.showPreloader();
    });
    this.listen(document, "turbo:submit-start", (event) => {
      if (!this.isMainFrameEvent(event)) this.showPreloader();
    });
    this.listen(document, "turbo:load", () => this.hidePreloader());
    this.listen(document, "turbo:render", () => this.hidePreloader());
    this.listen(document, "turbo:frame-render", () => this.hidePreloader());
    this.listen(document, "turbo:frame-load", () => this.hidePreloader());
    this.listen(document, "turbo:submit-end", () => this.hidePreloader());
    this.listen(document, "turbo:fetch-request-error", () => this.hidePreloader());

    this.hidePreloader();
  }

  private showPreloader(): void {
    this.enablePreloaderMode();
    this.setStatus("loading");
    this.root.hidden = false;
    this.root.setAttribute("aria-hidden", "false");
  }

  private hidePreloader(): void {
    this.setStatus("idle");
    this.root.hidden = true;
    this.root.setAttribute("aria-hidden", "true");
  }

  private setStatus(status: PreloaderStatus): void {
    this.root.dataset.omStatus = status;
  }

  private enablePreloaderMode(): void {
    document.documentElement.setAttribute("data-preloader", "enable");
  }

  private isMainFrameEvent(event: Event): boolean {
    const target = event.target;
    if (!(target instanceof Element)) return false;
    return Boolean(target.closest(MAIN_FRAME_SELECTOR));
  }
}
