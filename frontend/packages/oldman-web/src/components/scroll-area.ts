import "./scroll-area.scss";
import SimpleBar from "simplebar";
import { Component, type ComponentOptions } from "../core/component/component";

type ScrollAreaForceVisible = boolean | "x" | "y";

interface SimpleBarRuntimeOptions {
  autoHide?: boolean;
  clickOnTrack?: boolean;
  forceVisible?: ScrollAreaForceVisible;
  scrollbarMaxSize?: number;
  scrollbarMinSize?: number;
}

export interface ScrollAreaOptions extends ComponentOptions {
  autoHide?: boolean;
  clickOnTrack?: boolean;
  forceVisible?: ScrollAreaForceVisible;
  scrollbarMaxSize?: number;
  scrollbarMinSize?: number;
}

export interface ScrollAreaReadyDetail<TComponent extends ScrollArea = ScrollArea> {
  component: TComponent;
  scrollElement: HTMLElement | null;
}

type SimpleBarOptionsDraft = {
  [TKey in keyof SimpleBarRuntimeOptions]: SimpleBarRuntimeOptions[TKey] | undefined;
};

/**
 * 封装 SimpleBar 的无头滚动区域组件，统一自定义滚动条的生命周期。
 */
export class ScrollArea extends Component {
  static readonly componentName = "scroll-area";

  private readonly configuredOptions: ScrollAreaOptions;
  private simplebar: SimpleBar | null = null;
  private previousSimplebarAttribute: string | null = null;

  /**
   * 创建滚动区域组件，可通过构造参数或 data-simplebar-* 属性配置。
   */
  constructor(root: HTMLElement, options: ScrollAreaOptions = {}) {
    super(root, options);
    this.configuredOptions = options;
  }

  /**
   * 初始化 SimpleBar，并写入 data-simplebar 状态。
   */
  override async mount(): Promise<void> {
    disableGlobalSimpleBarObserver();
    this.previousSimplebarAttribute = this.root.getAttribute("data-simplebar");
    this.simplebar = SimpleBar.instances.get(this.root) ?? new SimpleBar(this.root, this.resolveOptions());
    this.emit<ScrollAreaReadyDetail>("om:scroll-area:ready", {
      component: this,
      scrollElement: this.getScrollElement()
    });
  }

  /**
   * 销毁 SimpleBar，并恢复原始 data-simplebar 标记，避免页面复用时残留状态。
   */
  override async unmount(): Promise<void> {
    this.simplebar?.unMount();
    this.simplebar = null;

    if (this.previousSimplebarAttribute === null) {
      this.root.removeAttribute("data-simplebar");
      return;
    }

    this.root.setAttribute("data-simplebar", this.previousSimplebarAttribute);
  }

  /**
   * 重新计算滚动区域尺寸，供动态内容变化后调用。
   */
  recalculate(): void {
    this.simplebar?.recalculate();
  }

  /**
   * 返回 SimpleBar 创建的真实滚动元素。
   */
  getScrollElement(): HTMLElement | null {
    return this.simplebar?.getScrollElement() ?? null;
  }

  /**
   * 滚动到指定坐标，并允许调用方选择原生滚动行为。
   */
  scrollTo(options: ScrollToOptions): void {
    this.getScrollElement()?.scrollTo(options);
  }

  /**
   * 合并构造参数与 data-simplebar-* 属性，构造参数优先级更高。
   */
  private resolveOptions(): SimpleBarRuntimeOptions {
    const dataOptions = SimpleBar.getOptions(this.root.attributes);
    return {
      ...dataOptions,
      ...definedOptions({
        autoHide: this.configuredOptions.autoHide,
        clickOnTrack: this.configuredOptions.clickOnTrack,
        forceVisible: this.configuredOptions.forceVisible,
        scrollbarMaxSize: this.configuredOptions.scrollbarMaxSize,
        scrollbarMinSize: this.configuredOptions.scrollbarMinSize
      })
    };
  }
}

/**
 * 删除 undefined 配置项，避免覆盖 SimpleBar 的默认值。
 */
function definedOptions(options: SimpleBarOptionsDraft): SimpleBarRuntimeOptions {
  return Object.fromEntries(Object.entries(options).filter(([, value]) => value !== undefined)) as SimpleBarRuntimeOptions;
}

/**
 * 关闭 SimpleBar 主包的全局 DOM observer，保留 Oldman 组件生命周期的唯一控制权。
 */
function disableGlobalSimpleBarObserver(): void {
  SimpleBar.removeObserver();
  document.removeEventListener("DOMContentLoaded", SimpleBar.initDOMLoadedElements);
  window.removeEventListener("load", SimpleBar.initDOMLoadedElements);
}
