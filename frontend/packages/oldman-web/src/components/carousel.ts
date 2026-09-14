import Swiper from "swiper";
import { A11y, Keyboard, Navigation, Pagination } from "swiper/modules";
import type { SwiperOptions } from "swiper/types";
import "./carousel.scss";
import { Component, type ComponentOptions } from "../core/component/component";

export interface CarouselOptions extends ComponentOptions {
  options?: SwiperOptions;
}

/** 管理响应式横向内容浏览及其 Swiper 生命周期。 */
export class Carousel extends Component {
  static readonly componentName = "carousel";

  private readonly configuredOptions: SwiperOptions | undefined;
  private swiper: Swiper | null = null;

  constructor(root: HTMLElement, options: CarouselOptions = {}) {
    super(root, options);
    this.configuredOptions = options.options;
  }

  /** 初始化触摸、键盘、前后按钮和分页能力。 */
  override async mount(): Promise<void> {
    const viewport = this.root.querySelector<HTMLElement>("[data-om-carousel-viewport]");
    if (!viewport) throw new Error("Carousel requires data-om-carousel-viewport");

    const previous = this.root.querySelector<HTMLElement>("[data-om-carousel-prev]");
    const next = this.root.querySelector<HTMLElement>("[data-om-carousel-next]");
    const pagination = this.root.querySelector<HTMLElement>("[data-om-carousel-pagination]");

    this.swiper = new Swiper(viewport, {
      ...this.readOptions(),
      a11y: { enabled: true },
      keyboard: { enabled: true, onlyInViewport: true },
      modules: [A11y, Keyboard, Navigation, Pagination],
      navigation: previous && next ? { nextEl: next, prevEl: previous } : false,
      pagination: pagination ? { clickable: true, el: pagination } : false
    });
    this.root.dataset.omCarouselState = "ready";
  }

  /** 销毁 Swiper 创建的状态、事件和样式。 */
  override async unmount(): Promise<void> {
    this.swiper?.destroy(true, true);
    this.swiper = null;
    delete this.root.dataset.omCarouselState;
  }

  /** Refresh layout and move to a zero-based slide without exposing Swiper. */
  slideTo(index: number, speed = 0): void {
    if (!Number.isInteger(index) || index < 0) throw new RangeError("Carousel slide index must be a non-negative integer");
    if (!this.swiper) throw new Error("Carousel is not mounted");
    this.swiper.update();
    this.swiper.slideTo(index, speed);
  }

  /** 读取构造参数或声明式 JSON 配置。 */
  private readOptions(): SwiperOptions {
    if (this.configuredOptions) return this.configuredOptions;
    const raw = this.root.getAttribute("data-om-carousel-options");
    return raw ? JSON.parse(raw) as SwiperOptions : {};
  }
}
