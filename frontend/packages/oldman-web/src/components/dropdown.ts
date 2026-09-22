import { Component } from "../core/component/component";
import { listNavigationIndex, querySelfOrDescendant, setHidden } from "../core/dom/helpers";
import { positionFloatingElement, resetFloatingPosition } from "../core/dom/floating";

const DROPDOWN_MENU_SELECTOR = "[data-om-dropdown-menu], .om-dropdown-menu";
const DROPDOWN_TOGGLE_SELECTOR = "[data-om-dropdown-toggle]";
const MENU_ITEM_SELECTOR = 'a[href], button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])';
const NAVIGATION_KEYS = new Set(["ArrowDown", "ArrowUp", "Home", "End"]);

export class Dropdown extends Component {
  static readonly componentName = "dropdown";

  /**
   * 注册下拉触发器、外部点击、Escape 和菜单内的方向键 / Home / End 处理器。
   */
  async mount(): Promise<void> {
    this.on("click", DROPDOWN_TOGGLE_SELECTOR, (event) => {
      event.preventDefault();
      this.toggleOpen();
    });

    this.listen<KeyboardEvent>(this.root, "keydown", (event) => this.navigateWithKeys(event));

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
    // 捕获阶段监听 document 的滚动是必要的:浮层锚定在触发元素上,而滚动可能发生在任何
    // 祖先容器里,冒泡阶段收不到。不是性能问题:`scroll` 事件本来就不可取消,passive 与否
    // 对它没有意义;`reposition()` 第一件事是判断是否打开,关闭时直接返回。
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
   * Arrow keys open the menu from its toggle and move between items; Home and End jump to the ends.
   * Focus stops at either end instead of wrapping, so a held key cannot loop past the last item.
   */
  private navigateWithKeys(event: KeyboardEvent): void {
    if (!NAVIGATION_KEYS.has(event.key)) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    const menu = this.menu();
    if (!menu) return;

    if (target.closest(DROPDOWN_TOGGLE_SELECTOR)) {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      if (!this.isOpen()) this.toggleOpen(true);
      this.focusItem(event.key === "ArrowUp" ? Number.MAX_SAFE_INTEGER : 0);
      return;
    }

    if (!this.isOpen() || !menu.contains(target)) return;
    const items = this.menuItems();
    const current = items.findIndex((item) => item === target || item.contains(target));
    const next = listNavigationIndex(event.key, current, items.length);
    if (next === null) return;
    event.preventDefault();
    items[next]?.focus();
  }

  /** Focusable items of the open menu, in document order, skipping hidden ones. */
  private menuItems(): HTMLElement[] {
    const menu = this.menu();
    if (!menu) return [];
    return Array.from(menu.querySelectorAll<HTMLElement>(MENU_ITEM_SELECTOR)).filter(
      (item) => !item.hidden && !item.closest("[hidden]")
    );
  }

  private focusItem(index: number): void {
    const items = this.menuItems();
    if (items.length === 0) return;
    items[Math.max(0, Math.min(items.length - 1, index))]?.focus();
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
