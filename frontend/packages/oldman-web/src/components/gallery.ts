import { Component } from "../core/component/component";
import { setHidden } from "../core/dom/helpers";
import type { Carousel } from "./carousel";

const ITEM_SELECTOR = "[data-om-gallery-item]";
const IMAGE_SELECTOR = "[data-om-gallery-image]";
const CAROUSEL_SELECTOR = "[data-om-gallery-carousel]";

/** Coordinate gallery thumbnails with a nested Modal and Carousel. */
export class Gallery extends Component {
  static readonly componentName = "gallery";
  private selectedIndex = 0;

  override async mount(): Promise<void> {
    this.on("click", ITEM_SELECTOR, (_event, item) => {
      const index = Number((item as HTMLElement).dataset.omGalleryIndex);
      if (!Number.isInteger(index) || index < 0) throw new Error("Gallery item requires a non-negative data-om-gallery-index");
      this.selectedIndex = index;
    });
    this.listen<CustomEvent>(this.root, "om:modal:open", () => this.carousel().slideTo(this.selectedIndex));
    this.listen(this.root, "error", (event) => this.setImageFailed(event, true), { capture: true });
    this.listen(this.root, "load", (event) => this.setImageFailed(event, false), { capture: true });
    for (const image of this.root.querySelectorAll<HTMLImageElement>(IMAGE_SELECTOR)) {
      if (image.complete) this.updateImageState(image, image.naturalWidth === 0);
    }
  }

  private carousel(): Carousel {
    const root = this.root.querySelector<HTMLElement>(CAROUSEL_SELECTOR);
    const carousel = root && this.manager?.get<Carousel>(root);
    if (!carousel) throw new Error("Gallery requires a mounted data-om-gallery-carousel");
    return carousel;
  }

  private setImageFailed(event: Event, failed: boolean): void {
    const image = event.target;
    if (!(image instanceof HTMLImageElement) || !image.matches(IMAGE_SELECTOR)) return;
    this.updateImageState(image, failed);
  }

  private updateImageState(image: HTMLImageElement, failed: boolean): void {
    image.hidden = failed;
    const fallback = image.parentElement?.querySelector<HTMLElement>("[data-om-gallery-fallback]");
    if (fallback) setHidden(fallback, !failed);
  }
}
