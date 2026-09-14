import { Component, type ComponentOptions } from "../core/component/component";

export interface BackToTopOptions extends ComponentOptions {
  behavior?: ScrollBehavior;
  threshold?: number;
}

export interface BackToTopVisibilityDetail<TComponent extends BackToTop = BackToTop> {
  component: TComponent;
  visible: boolean;
}

/**
 * 为返回顶部按钮提供无头滚动阈值、可见状态和点击回到顶部能力。
 */
export class BackToTop extends Component {
  static readonly componentName = "back-to-top";

  private readonly behavior: ScrollBehavior;
  private readonly threshold: number;
  private visible = false;

  /**
   * 创建返回顶部组件，并允许项目侧配置滚动阈值和滚动行为。
   */
  constructor(root: HTMLElement, options: BackToTopOptions = {}) {
    super(root, options);
    this.behavior = options.behavior ?? "auto";
    this.threshold = options.threshold ?? 100;
  }

  /**
   * 绑定窗口滚动与按钮点击事件，并同步初始可见状态。
   */
  override async mount(): Promise<void> {
    this.listen(window, "scroll", () => this.updateVisibility());
    this.listen(this.root, "click", (event) => {
      event.preventDefault();
      this.scrollToTop();
    });
    this.updateVisibility();
  }

  /**
   * 根据当前滚动位置刷新按钮状态。
   */
  updateVisibility(): void {
    this.setVisible(this.currentScrollTop() > this.threshold);
  }

  /**
   * 设置组件可见状态，默认只使用无样式语义属性。
   */
  protected setVisible(visible: boolean): void {
    if (this.visible === visible) return;

    this.visible = visible;
    this.root.hidden = !visible;
    this.root.dataset.omState = visible ? "visible" : "hidden";
    this.root.setAttribute("aria-hidden", String(!visible));
    this.emit<BackToTopVisibilityDetail>("om:back-to-top:visibility", { component: this, visible });
  }

  /**
   * 将页面滚动回顶部，兼容浏览器的 body/documentElement 滚动实现差异。
   */
  protected scrollToTop(): void {
    window.scrollTo({ top: 0, behavior: this.behavior });
    document.body.scrollTop = 0;
    document.documentElement.scrollTop = 0;
  }

  /**
   * 读取当前垂直滚动位置。
   */
  protected currentScrollTop(): number {
    return window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
  }
}
