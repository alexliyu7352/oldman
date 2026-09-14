import { Component } from "../core/component/component";
import { querySelfOrDescendant, setHidden } from "../core/dom/helpers";
import { positionFloatingElement, resetFloatingPosition } from "../core/dom/floating";

const DROPDOWN_MENU_SELECTOR = "[data-om-dropdown-menu], .om-dropdown-menu";
const DROPDOWN_TOGGLE_SELECTOR = "[data-om-dropdown-toggle]";

export class Dropdown extends Component {
  static readonly componentName = "dropdown";

  /**
   * 注册下拉触发器、外部点击和 Escape 键处理器。
   */
  async mount(): Promise<void> {
    this.on("click", DROPDOWN_TOGGLE_SELECTOR, (event) => {
      event.preventDefault();
      this.toggleOpen();
    });

    this.listen<MouseEvent>(document, "click", (event) => {
      if (this.isOutsideClick(event)) this.close();
    });

    // Tab may leave the menu without closing it; only own Escape in the same Modal.
    this.listen<KeyboardEvent>(document, "keydown", (event) => {
      if (event.key !== "Escape" || !this.isOpen()) return;
      const target = event.target;
      if (!(target instanceof Element)
        || target.closest('[aria-modal="true"]') !== this.root.closest('[aria-modal="true"]')) return;
      event.stopImmediatePropagation();
      this.close();
      this.toggleButton()?.focus();
    }, { capture: true });

    this.listen(window, "resize", () => this.reposition());
    this.listen(document, "scroll", () => this.reposition(), { capture: true });
    this.cleanup(() => this.close());
  }

  /**
   * 切换下拉菜单显隐；传入布尔值时强制设置目标状态。
   */
  toggleOpen(force?: boolean): void {
    const menu = this.menu();
    if (!menu) return;

    const expanded = force ?? (menu.classList.contains("hidden") || menu.hidden || !menu.classList.contains("show"));

    menu.classList.toggle("hidden", !expanded);
    menu.classList.toggle("show", expanded);
    setHidden(menu, !expanded);
    this.toggleButton()?.setAttribute("aria-expanded", String(expanded));
    this.root.classList.toggle("show", expanded);

    if (expanded) {
      this.positionMenu(menu);
    } else {
      this.resetMenuPosition(menu);
    }
  }

  /**
   * 隐藏下拉菜单，并同步触发按钮的折叠状态。
   */
  close(): void {
    this.toggleOpen(false);
  }

  /**
   * 在组件根节点内查找下拉菜单元素。
   */
  private menu(): HTMLElement | null {
    return querySelfOrDescendant<HTMLElement>(this.root, DROPDOWN_MENU_SELECTOR);
  }

  /**
   * 在组件根节点内查找下拉触发按钮。
   */
  private toggleButton(): HTMLElement | null {
    return querySelfOrDescendant<HTMLElement>(this.root, DROPDOWN_TOGGLE_SELECTOR);
  }

  /**
   * 将菜单钳制在当前 viewport 内，避免表格滚动容器和右边缘裁切行操作菜单。
   */
  private positionMenu(menu: HTMLElement): void {
    const toggle = this.toggleButton();
    if (!toggle) return;
    positionFloatingElement(
      toggle,
      menu,
      menu.classList.contains("om-dropdown-menu-end") ? "bottom-end" : "bottom-start",
      { preserveWidth: true }
    );
  }

  /**
   * 关闭菜单时恢复到样式表控制，避免下次挂载保留 viewport 位置。
   */
  private resetMenuPosition(menu: HTMLElement): void {
    resetFloatingPosition(menu);
  }

  /** Keep an open menu anchored while its viewport position changes. */
  private reposition(): void {
    const menu = this.menu();
    if (menu && this.isOpen()) this.positionMenu(menu);
  }

  private isOpen(): boolean {
    const menu = this.menu();
    return Boolean(menu && !menu.hidden && menu.classList.contains("show"));
  }

  /**
   * 判断文档点击是否发生在当前下拉组件外部。
   */
  private isOutsideClick(event: MouseEvent): boolean {
    const target = event.target;
    return target instanceof Node && !this.root.contains(target);
  }
}
