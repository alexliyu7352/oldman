import { Component } from "../core/component/component";
import { querySelfOrDescendant, setHidden } from "../core/dom/helpers";

const IMAGE_SELECTOR = "[data-om-avatar-image]";
const FALLBACK_SELECTOR = "[data-om-avatar-fallback]";

/** 在头像图片缺失或加载失败时显示服务端提供的回退内容。 */
export class Avatar extends Component {
  static readonly componentName = "avatar";

  /** 监听图片结果，并以真实加载状态切换 fallback。 */
  override async mount(): Promise<void> {
    const image = querySelfOrDescendant<HTMLImageElement>(this.root, IMAGE_SELECTOR);
    const fallback = querySelfOrDescendant<HTMLElement>(this.root, FALLBACK_SELECTOR);
    if (!image || !fallback) return;

    this.listen(image, "load", () => this.showImage(image, fallback));
    this.listen(image, "error", () => this.showFallback(image, fallback));

    if (image.complete) {
      if (image.naturalWidth > 0) this.showImage(image, fallback);
      else this.showFallback(image, fallback);
    }
  }

  private showImage(image: HTMLImageElement, fallback: HTMLElement): void {
    setHidden(image, false);
    setHidden(fallback, true);
    this.root.dataset.omAvatarState = "image";
  }

  private showFallback(image: HTMLImageElement, fallback: HTMLElement): void {
    setHidden(image, true);
    setHidden(fallback, false);
    this.root.dataset.omAvatarState = "fallback";
  }
}
