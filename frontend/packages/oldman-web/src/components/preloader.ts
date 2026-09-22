import { Component } from "../core/component/component";

type PreloaderStatus = "idle" | "loading";
type ProgressStatus = "idle" | "loading" | "done";

const PROGRESS_SELECTOR = "[data-om-page-progress]";

/**
 * 页面级加载反馈：初次加载时接管全屏 preloader，之后每次 Turbo 请求只驱动顶部 2px 进度条，
 * 旧页面在新内容到达前保持可见。
 */
export class Preloader extends Component {
  static readonly componentName = "preloader";

  override async mount(): Promise<void> {
    this.enablePreloaderMode();
    this.listen(document, "turbo:before-visit", () => this.startProgress());
    this.listen(document, "turbo:before-fetch-request", () => this.startProgress());
    this.listen(document, "turbo:submit-start", () => this.startProgress());
    this.listen(document, "turbo:load", () => this.finishLoading());
    this.listen(document, "turbo:render", () => this.finishLoading());
    this.listen(document, "turbo:frame-render", () => this.finishLoading());
    this.listen(document, "turbo:frame-load", () => this.finishLoading());
    this.listen(document, "turbo:submit-end", () => this.finishLoading());
    this.listen(document, "turbo:fetch-request-error", () => this.finishLoading());

    this.hidePreloader();
    this.setProgressStatus("idle");
  }

  override async beforeUnmount(): Promise<void> {
    this.setProgressStatus("idle");
  }

  private startProgress(): void {
    this.setProgressStatus("loading");
  }

  private finishLoading(): void {
    this.hidePreloader();
    if (this.progressElement()?.dataset.omStatus === "loading") this.setProgressStatus("done");
  }

  private hidePreloader(): void {
    this.setStatus("idle");
    this.root.hidden = true;
    this.root.setAttribute("aria-hidden", "true");
  }

  private setStatus(status: PreloaderStatus): void {
    this.root.dataset.omStatus = status;
  }

  private setProgressStatus(status: ProgressStatus): void {
    const bar = this.progressElement();
    if (bar) bar.dataset.omStatus = status;
  }

  private progressElement(): HTMLElement | null {
    return document.querySelector<HTMLElement>(PROGRESS_SELECTOR);
  }

  private enablePreloaderMode(): void {
    document.documentElement.setAttribute("data-preloader", "enable");
  }
}
