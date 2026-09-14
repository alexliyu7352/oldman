import { Component, type ComponentOptions } from "../core/component/component";
import { setHidden } from "../core/dom/helpers";

const MENU_ITEM_SELECTOR = "[data-om-menu-item]";
const MENU_PANEL_SELECTOR = "[data-om-menu-panel]";
const MENU_TOGGLE_SELECTOR = "[data-om-menu-toggle]";
const SIDEBAR_BACKDROP_SELECTOR = "[data-om-sidebar-backdrop]";
const SIDEBAR_TOGGLE_SELECTOR = "[data-om-sidebar-toggle]";
const DEFAULT_SIDEBAR_SIZE = "lg";
const COMPACT_SIDEBAR_SIZE = "sm";
const MOBILE_SIDEBAR_WIDTH = 767;

export class SidebarMenu extends Component {
  static readonly componentName = "sidebar-menu";
  readonly defaultSidebarSize: string;
  readonly menuPanelSelector: string;
  readonly menuRootItemSelector: string;

  constructor(root: HTMLElement, options: ComponentOptions = {}) {
    super(root, options);
    this.defaultSidebarSize = root.dataset.omDefaultSidebarSize ?? DEFAULT_SIDEBAR_SIZE;
    this.menuPanelSelector = root.dataset.omMenuPanelSelector ?? MENU_PANEL_SELECTOR;
    this.menuRootItemSelector = root.dataset.omMenuRootItemSelector ?? MENU_ITEM_SELECTOR;
  }

  /**
   * 注册多级菜单切换，以及文档级移动端侧栏开关。
   */
  async mount(): Promise<void> {
    // The backdrop survives main Frame replacement; its owning component closes it.
    this.closeMobileSidebar();
    this.cleanup(() => this.closeMobileSidebar());
    this.on("click", MENU_TOGGLE_SELECTOR, (event, toggle) => {
      event.preventDefault();
      if (!(toggle instanceof HTMLElement)) return;
      this.toggleMenu(toggle);
    });

    this.listen<MouseEvent>(document, "click", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (!target.closest(SIDEBAR_TOGGLE_SELECTOR)) return;

      event.preventDefault();
      this.toggleSidebar(target.closest<HTMLElement>(SIDEBAR_TOGGLE_SELECTOR));
    });

    this.listen<MouseEvent>(document, "click", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (!target.closest(SIDEBAR_BACKDROP_SELECTOR)) return;

      event.preventDefault();
      this.closeMobileSidebar();
    });
  }

  /**
   * 切换子菜单面板，并同步按钮与菜单项状态。
   */
  toggleMenu(toggle: HTMLElement): void {
    const item = toggle.closest<HTMLElement>(this.menuRootItemSelector);
    const panel = item?.querySelector<HTMLElement>(this.menuPanelSelector);
    if (!item || !panel) return;

    const expanded = panel.hidden || panel.classList.contains("hidden") || !panel.classList.contains("show");
    if (expanded) this.closeSiblingMenus(item);
    panel.classList.toggle("hidden", !expanded);
    panel.classList.toggle("show", expanded);
    setHidden(panel, !expanded);
    toggle.setAttribute("aria-expanded", String(expanded));
    item.classList.toggle("open", expanded);
  }

  /**
   * 保持同层主菜单互斥，避免侧栏展开后产生长而混乱的菜单堆叠。
   */
  private closeSiblingMenus(item: HTMLElement): void {
    const parent = item.parentElement;
    if (!parent) return;

    for (const sibling of Array.from(parent.children)) {
      if (!(sibling instanceof HTMLElement) || sibling === item) continue;

      const siblingPanel = sibling.querySelector<HTMLElement>(this.menuPanelSelector);
      const siblingToggle = sibling.querySelector<HTMLElement>(MENU_TOGGLE_SELECTOR);
      if (!siblingPanel || !siblingToggle) continue;

      siblingPanel.classList.add("hidden");
      siblingPanel.classList.remove("show");
      setHidden(siblingPanel, true);
      siblingToggle.setAttribute("aria-expanded", "false");
      sibling.classList.remove("open");
    }
  }

  /**
   * 标记移动端侧栏为打开状态，并显示共享遮罩层。
   */
  private openMobileSidebar(): void {
    document.documentElement.dataset.omSidebarOpen = "true";
    document.body.classList.add("vertical-sidebar-enable");
    const backdrop = this.sidebarBackdrop();
    if (!backdrop) return;

    backdrop.classList.remove("hidden");
    setHidden(backdrop, false);
  }

  /**
   * 清除移动端侧栏状态，并隐藏共享遮罩层。
   */
  private closeMobileSidebar(): void {
    delete document.documentElement.dataset.omSidebarOpen;
    document.body.classList.remove("vertical-sidebar-enable");
    const backdrop = this.sidebarBackdrop();
    if (!backdrop) return;

    backdrop.classList.add("hidden");
    setHidden(backdrop, true);
  }

  /**
   * 根据当前视口复刻 Oldman 桌面折叠和移动端抽屉行为。
   */
  private toggleSidebar(trigger: HTMLElement | null): void {
    const width = document.documentElement.clientWidth;
    const hamburgerIcon = trigger?.querySelector<HTMLElement>(".hamburger-icon");

    if (width > MOBILE_SIDEBAR_WIDTH) {
      hamburgerIcon?.classList.toggle("open");
    }

    if (width <= MOBILE_SIDEBAR_WIDTH) {
      if (document.documentElement.dataset.omSidebarOpen === "true") {
        this.closeMobileSidebar();
      } else {
        document.documentElement.setAttribute("data-sidebar-size", this.defaultSidebarSize);
        this.openMobileSidebar();
      }
      return;
    }

    this.closeMobileSidebar();
    const current = document.documentElement.getAttribute("data-sidebar-size") || this.defaultSidebarSize;
    const alternateSize = this.defaultSidebarSize === COMPACT_SIDEBAR_SIZE
      ? DEFAULT_SIDEBAR_SIZE
      : COMPACT_SIDEBAR_SIZE;
    const next = current === alternateSize ? this.defaultSidebarSize : alternateSize;
    document.documentElement.setAttribute("data-sidebar-size", next);
  }

  /**
   * 查找全局移动端侧栏遮罩层。
   */
  private sidebarBackdrop(): HTMLElement | null {
    return document.querySelector<HTMLElement>(SIDEBAR_BACKDROP_SELECTOR);
  }
}
