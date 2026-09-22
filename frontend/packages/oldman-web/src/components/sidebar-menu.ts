import { Component, type ComponentOptions } from "../core/component/component";
import { positionFloatingElement } from "../core/dom/floating";
import { listNavigationIndex, setHidden } from "../core/dom/helpers";

const MENU_ITEM_SELECTOR = "[data-om-menu-item]";
const MENU_PANEL_SELECTOR = "[data-om-menu-panel]";
const MENU_TOGGLE_SELECTOR = "[data-om-menu-toggle]";
const SIDEBAR_BACKDROP_SELECTOR = "[data-om-sidebar-backdrop]";
const SIDEBAR_TOGGLE_SELECTOR = "[data-om-sidebar-toggle]";
const DEFAULT_SIDEBAR_SIZE = "lg";
const COMPACT_SIDEBAR_SIZE = "sm";
const MOBILE_SIDEBAR_WIDTH = 767;
/* The collapsed rail only exists from this width up (the stylesheet's `lg` breakpoint). */
const COLLAPSED_RAIL_MIN_WIDTH = 1024;
const FLYOUT_LINK_SELECTOR = ".oldman-menu-flyout-link";
const FLYOUT_OPEN_CLASS = "flyout-open";
const FLYOUT_HOVER_DELAY_MS = 200;
const FLYOUT_CLOSE_DELAY_MS = 150;

export class SidebarMenu extends Component {
  static readonly componentName = "sidebar-menu";
  readonly defaultSidebarSize: string;
  readonly menuPanelSelector: string;
  readonly menuRootItemSelector: string;
  private flyout: HTMLElement | null = null;
  private flyoutItem: HTMLElement | null = null;
  private pendingFlyoutItem: HTMLElement | null = null;
  private flyoutOpenTimer: number | null = null;
  private flyoutCloseTimer: number | null = null;

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
      const item = this.flyoutCandidate(toggle);
      if (item) {
        // Hover usually opened the flyout already; a click on the same icon keeps it open (openFlyout is
        // idempotent). Outside clicks, Escape and the links are what close it.
        this.openFlyout(item);
        return;
      }
      this.toggleMenu(toggle);
    });

    this.bindFlyout();

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
   * Collapsed rail (48px icons on desktop): a group cannot expand inline, so its links open in a
   * flyout beside the icon. Hover waits like a tooltip, click and the arrow keys open at once.
   */
  private bindFlyout(): void {
    this.on("pointerover", MENU_TOGGLE_SELECTOR, (_event, toggle) => {
      if (!(toggle instanceof HTMLElement)) return;
      const item = this.flyoutCandidate(toggle);
      if (!item) return;
      this.cancelFlyoutClose();
      if (this.flyoutItem === item || this.pendingFlyoutItem === item) return;
      this.scheduleFlyoutOpen(item);
    });

    this.on("pointerout", MENU_TOGGLE_SELECTOR, (event, toggle) => {
      if (!(toggle instanceof HTMLElement)) return;
      const next = event.relatedTarget;
      if (next instanceof Node && toggle.contains(next)) return;
      this.cancelFlyoutOpen();
      if (this.flyout && !(next instanceof Node && this.flyout.contains(next))) this.scheduleFlyoutClose();
    });

    this.on("keydown", MENU_TOGGLE_SELECTOR, (event, toggle) => {
      if (!(toggle instanceof HTMLElement) || (event.key !== "ArrowRight" && event.key !== "ArrowDown")) return;
      const item = this.flyoutCandidate(toggle);
      if (!item) return;
      event.preventDefault();
      this.openFlyout(item);
      this.flyoutLinks()[0]?.focus();
    });

    this.listen<MouseEvent>(document, "click", (event) => {
      const target = event.target;
      if (!this.flyout || !(target instanceof Node)) return;
      if (this.flyout.contains(target) || this.flyoutItem?.contains(target)) return;
      this.closeFlyout();
    });

    this.listen<KeyboardEvent>(document, "keydown", (event) => {
      if (event.key !== "Escape" || !this.flyout) return;
      event.stopImmediatePropagation();
      const toggle = this.flyoutItem?.querySelector<HTMLElement>(MENU_TOGGLE_SELECTOR);
      this.closeFlyout();
      toggle?.focus();
    }, { capture: true });

    this.listen(document, "turbo:frame-render", () => this.closeFlyout());
    this.listen(window, "resize", () => this.closeFlyout());
    this.cleanup(() => this.closeFlyout());
  }

  /** The group item behind a toggle when the rail is collapsed and the group has links to show. */
  private flyoutCandidate(toggle: HTMLElement): HTMLElement | null {
    if (!this.isCollapsedRail()) return null;
    const item = toggle.closest<HTMLElement>(this.menuRootItemSelector);
    const panel = item?.querySelector<HTMLElement>(this.menuPanelSelector);
    return item && panel?.querySelector("a[href]") ? item : null;
  }

  private isCollapsedRail(): boolean {
    return document.documentElement.getAttribute("data-sidebar-size") === COMPACT_SIDEBAR_SIZE
      && window.innerWidth >= COLLAPSED_RAIL_MIN_WIDTH;
  }

  private scheduleFlyoutOpen(item: HTMLElement): void {
    this.cancelFlyoutOpen();
    this.pendingFlyoutItem = item;
    this.flyoutOpenTimer = window.setTimeout(() => {
      this.flyoutOpenTimer = null;
      this.pendingFlyoutItem = null;
      this.openFlyout(item);
    }, FLYOUT_HOVER_DELAY_MS);
  }

  private cancelFlyoutOpen(): void {
    this.pendingFlyoutItem = null;
    if (this.flyoutOpenTimer === null) return;
    window.clearTimeout(this.flyoutOpenTimer);
    this.flyoutOpenTimer = null;
  }

  /** Leaving the icon or the panel closes after a short grace so the pointer can cross the gap. */
  private scheduleFlyoutClose(): void {
    this.cancelFlyoutClose();
    this.flyoutCloseTimer = window.setTimeout(() => {
      this.flyoutCloseTimer = null;
      this.closeFlyout();
    }, FLYOUT_CLOSE_DELAY_MS);
  }

  private cancelFlyoutClose(): void {
    if (this.flyoutCloseTimer === null) return;
    window.clearTimeout(this.flyoutCloseTimer);
    this.flyoutCloseTimer = null;
  }

  /** Build the flyout from the group's own links (clones keep href and Turbo attributes) on <body>. */
  openFlyout(item: HTMLElement): void {
    this.cancelFlyoutOpen();
    this.cancelFlyoutClose();
    if (this.flyoutItem === item && this.flyout) return;
    this.closeFlyout();

    const toggle = item.querySelector<HTMLElement>(MENU_TOGGLE_SELECTOR);
    const panel = item.querySelector<HTMLElement>(this.menuPanelSelector);
    if (!toggle || !panel) return;

    const flyout = document.createElement("div");
    flyout.className = "oldman-menu-flyout";
    flyout.setAttribute("data-om-menu-flyout", "");
    flyout.setAttribute("role", "menu");
    const title = this.menuTitle(toggle);
    if (title) {
      const heading = document.createElement("div");
      heading.className = "oldman-menu-flyout-title";
      heading.textContent = title;
      flyout.append(heading);
      flyout.setAttribute("aria-label", title);
    }
    const list = document.createElement("ul");
    list.className = "oldman-menu-flyout-list";
    for (const link of panel.querySelectorAll<HTMLAnchorElement>("a[href]")) {
      const clone = link.cloneNode(true) as HTMLAnchorElement;
      clone.className = `oldman-menu-flyout-link${link.classList.contains("active") ? " active" : ""}`;
      clone.setAttribute("role", "menuitem");
      // Plain text: the collapsed-rail stylesheet hides every `.menu-text` span, clones included.
      clone.replaceChildren(document.createTextNode(link.textContent?.trim() ?? ""));
      const entry = document.createElement("li");
      entry.append(clone);
      list.append(entry);
    }
    flyout.append(list);

    flyout.addEventListener("pointerenter", () => this.cancelFlyoutClose());
    flyout.addEventListener("pointerleave", () => this.scheduleFlyoutClose());
    flyout.addEventListener("click", (event) => {
      if (event.target instanceof Element && event.target.closest("a[href]")) this.closeFlyout();
    });
    flyout.addEventListener("keydown", (event) => this.navigateFlyout(event, toggle));
    flyout.addEventListener("focusout", (event) => {
      const next = event.relatedTarget;
      if (next instanceof Node && (flyout.contains(next) || item.contains(next))) return;
      this.closeFlyout();
    });

    document.body.append(flyout);
    positionFloatingElement(toggle, flyout, "right-start", { gap: 12 });
    toggle.setAttribute("aria-expanded", "true");
    item.classList.add(FLYOUT_OPEN_CLASS);
    this.flyout = flyout;
    this.flyoutItem = item;
  }

  closeFlyout(): void {
    this.cancelFlyoutOpen();
    this.cancelFlyoutClose();
    const flyout = this.flyout;
    const item = this.flyoutItem;
    this.flyout = null;
    this.flyoutItem = null;
    if (!flyout || !item) return;

    flyout.remove();
    item.classList.remove(FLYOUT_OPEN_CLASS);
    const toggle = item.querySelector<HTMLElement>(MENU_TOGGLE_SELECTOR);
    const panel = item.querySelector<HTMLElement>(this.menuPanelSelector);
    const inlineOpen = Boolean(panel && !panel.hidden && panel.classList.contains("show"));
    toggle?.setAttribute("aria-expanded", String(inlineOpen));
  }

  private navigateFlyout(event: KeyboardEvent, toggle: HTMLElement): void {
    if (event.key === "Escape" || event.key === "ArrowLeft") {
      event.preventDefault();
      event.stopPropagation();
      this.closeFlyout();
      toggle.focus();
      return;
    }
    const links = this.flyoutLinks();
    const current = links.findIndex((link) => link === document.activeElement || link.contains(document.activeElement));
    const next = listNavigationIndex(event.key, current, links.length);
    if (next === null) return;
    event.preventDefault();
    links[next]?.focus();
  }

  private flyoutLinks(): HTMLElement[] {
    return this.flyout ? Array.from(this.flyout.querySelectorAll<HTMLElement>(FLYOUT_LINK_SELECTOR)) : [];
  }

  private menuTitle(toggle: HTMLElement): string {
    return (
      toggle.querySelector<HTMLElement>(".menu-text")?.textContent?.trim()
      || toggle.getAttribute("aria-label")
      || toggle.textContent?.trim()
      || ""
    );
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
    this.closeFlyout();
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
