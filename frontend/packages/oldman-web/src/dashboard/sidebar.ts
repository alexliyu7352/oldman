import { Component, type ComponentOptions } from "../core/index";

export interface DashboardSidebarOptions extends ComponentOptions {
  activePath?: string;
  defaultDashboardPath?: string;
  defaultSidebarSize?: string;
  mainFrameSelector?: string;
  menuPanelSelector?: string;
  menuRootItemSelector?: string;
  navSelector?: string;
  scrollContainerSelector?: string;
  twoColumnMenuSelector?: string;
}

const DEFAULT_MAIN_FRAME_SELECTOR = "#oldman-main";
const DEFAULT_MENU_PANEL_SELECTOR = "[data-om-menu-panel]";
const DEFAULT_MENU_ROOT_ITEM_SELECTOR = "[data-om-menu-item], .nav-item";
const DEFAULT_NAV_SELECTOR = "#navbar-nav";
const SIDEBAR_MENU_SELECTOR = '[data-om-component~="sidebar-menu"]';
/** Fired on document after the sidebar re-evaluated which item is active. */
export const SIDEBAR_ACTIVE_CHANGE_EVENT = "om:sidebar:active-change";
const SCROLL_INTO_VIEW_MARGIN = 16;

interface SidebarMenuAttributes {
  defaultSidebarSize: string | null;
  menuPanelSelector: string | null;
  menuRootItemSelector: string | null;
}

export class DashboardSidebar extends Component {
  private readonly activePath: string | null;
  readonly defaultDashboardPath: string;
  readonly defaultSidebarSize: string;
  readonly mainFrameSelector: string;
  readonly menuPanelSelector: string;
  readonly menuRootItemSelector: string;
  readonly navSelector: string;
  readonly scrollContainerSelector: string;
  readonly twoColumnMenuSelector: string;
  private readonly configuredSidebarMenus = new Map<HTMLElement, SidebarMenuAttributes>();

  constructor(root: HTMLElement, options: DashboardSidebarOptions = {}) {
    super(root, options);
    this.activePath = options.activePath ?? null;
    this.defaultDashboardPath = options.defaultDashboardPath ?? "/";
    this.defaultSidebarSize = options.defaultSidebarSize ?? "lg";
    this.mainFrameSelector = this.page?.mainFrameSelector ?? options.mainFrameSelector ?? DEFAULT_MAIN_FRAME_SELECTOR;
    this.menuPanelSelector = options.menuPanelSelector ?? DEFAULT_MENU_PANEL_SELECTOR;
    this.menuRootItemSelector = options.menuRootItemSelector ?? DEFAULT_MENU_ROOT_ITEM_SELECTOR;
    this.navSelector = options.navSelector ?? DEFAULT_NAV_SELECTOR;
    this.scrollContainerSelector = options.scrollContainerSelector ?? ".oldman-sidebar-scroll, #scrollbar";
    this.twoColumnMenuSelector = options.twoColumnMenuSelector ?? "#two-column-menu";
  }

  override async mount(): Promise<void> {
    this.configureSidebarMenus();
    this.prepareVerticalSidebar();
    this.activateCurrentSidebarItem();
    this.bindDropdownViewportGuard();
    this.bindVerticalHoverToggle();
    this.bindMainFrameNavigationState();
    this.scrollActiveMenuIntoView();
  }

  override async beforeUnmount(): Promise<void> {
    for (const dropdown of this.root.querySelectorAll<HTMLElement>(".dropdown-custom-right")) {
      dropdown.classList.remove("dropdown-custom-right");
    }
    this.restoreSidebarMenuAttributes();
  }

  private configureSidebarMenus(): void {
    const sidebarMenus = Array.from(this.root.querySelectorAll<HTMLElement>(SIDEBAR_MENU_SELECTOR));
    if (this.root.matches(SIDEBAR_MENU_SELECTOR)) sidebarMenus.unshift(this.root);
    for (const sidebarMenu of sidebarMenus) {
      this.configuredSidebarMenus.set(sidebarMenu, {
        defaultSidebarSize: sidebarMenu.getAttribute("data-om-default-sidebar-size"),
        menuPanelSelector: sidebarMenu.getAttribute("data-om-menu-panel-selector"),
        menuRootItemSelector: sidebarMenu.getAttribute("data-om-menu-root-item-selector")
      });
      sidebarMenu.setAttribute("data-om-default-sidebar-size", this.defaultSidebarSize);
      sidebarMenu.setAttribute("data-om-menu-panel-selector", this.menuPanelSelector);
      sidebarMenu.setAttribute("data-om-menu-root-item-selector", this.menuRootItemSelector);
    }
  }

  private restoreSidebarMenuAttributes(): void {
    for (const [sidebarMenu, attributes] of this.configuredSidebarMenus) {
      this.restoreAttribute(sidebarMenu, "data-om-default-sidebar-size", attributes.defaultSidebarSize);
      this.restoreAttribute(sidebarMenu, "data-om-menu-panel-selector", attributes.menuPanelSelector);
      this.restoreAttribute(sidebarMenu, "data-om-menu-root-item-selector", attributes.menuRootItemSelector);
    }
    this.configuredSidebarMenus.clear();
  }

  private restoreAttribute(element: HTMLElement, name: string, value: string | null): void {
    if (value === null) {
      element.removeAttribute(name);
      return;
    }
    element.setAttribute(name, value);
  }

  private prepareVerticalSidebar(): void {
    const layout = document.documentElement.getAttribute("data-layout");
    if (layout !== "vertical" && layout !== "semibox") return;

    this.root.querySelector<HTMLElement>(this.twoColumnMenuSelector)?.replaceChildren();
  }

  private activateCurrentSidebarItem(): void {
    const sidebar = this.root.querySelector<HTMLElement>(this.navSelector);
    if (!sidebar) return;

    this.clearActiveSidebarItems(sidebar);
    const pathname = this.currentPathname();
    const exactPath = pathname === "/" ? this.defaultDashboardPath : pathname;
    const currentPaths = this.currentPagePaths();
    if (currentPaths.length === 0) {
      this.announceActiveChange();
      return;
    }

    const links = Array.from(sidebar.querySelectorAll<HTMLAnchorElement>("a[href]"));
    const activeLink =
      links.find((link) => link.getAttribute("href") === exactPath)
      ?? this.longestPathPrefixLink(links, pathname)
      ?? links.find((link) => currentPaths.includes(link.getAttribute("href") ?? ""));
    if (!activeLink) {
      this.announceActiveChange();
      return;
    }

    activeLink.classList.add("active");
    this.expandParentMenu(activeLink);
    this.announceActiveChange();
  }

  private announceActiveChange(): void {
    document.dispatchEvent(new CustomEvent(SIDEBAR_ACTIVE_CHANGE_EVENT));
  }

  private clearActiveSidebarItems(sidebar: HTMLElement): void {
    for (const link of sidebar.querySelectorAll<HTMLElement>("a.active")) {
      link.classList.remove("active");
    }
    for (const toggle of sidebar.querySelectorAll<HTMLElement>("[data-om-menu-toggle].active")) {
      toggle.classList.remove("active");
    }
    for (const item of sidebar.querySelectorAll<HTMLElement>(
      `:is(${this.menuRootItemSelector}).active, :is(${this.menuRootItemSelector}).open`
    )) {
      item.classList.remove("active", "open");
    }
    for (const expandedLink of sidebar.querySelectorAll<HTMLElement>('[data-om-menu-toggle][aria-expanded="true"]')) {
      expandedLink.setAttribute("aria-expanded", "false");
    }
    for (const dropdown of sidebar.querySelectorAll<HTMLElement>(this.menuPanelSelector)) {
      if (!dropdown.classList.contains("show")) continue;
      dropdown.classList.remove("show");
      dropdown.classList.add("hidden");
      dropdown.hidden = true;
    }
  }

  private currentPagePaths(): string[] {
    const currentPathname = this.currentPathname();
    const pathname = currentPathname === "/" ? "/index.html" : currentPathname;
    if (currentPathname === "/") return ["/", this.defaultDashboardPath, this.defaultDashboardPath.replace(/^\//, "")];

    const filename = pathname.substring(pathname.lastIndexOf("/") + 1);
    const rootPath = `/${pathname.split("/").filter(Boolean)[0] ?? ""}`;
    return Array.from(new Set([pathname, rootPath, filename].filter(Boolean)));
  }

  private currentPathname(): string {
    return this.activePath ?? location.pathname;
  }

  private longestPathPrefixLink(links: HTMLAnchorElement[], pathname: string): HTMLAnchorElement | undefined {
    const normalizedPathname = this.normalizePathname(pathname);
    return links
      .map((link) => ({ link, pathname: this.linkPathname(link) }))
      .filter(({ pathname: linkPathname }) =>
        linkPathname !== null
        && linkPathname !== "/"
        && (normalizedPathname === linkPathname || normalizedPathname.startsWith(`${linkPathname}/`))
      )
      .sort((left, right) => right.pathname!.length - left.pathname!.length)[0]?.link;
  }

  private linkPathname(link: HTMLAnchorElement): string | null {
    const href = link.getAttribute("href");
    if (!href || href.startsWith("#")) return null;

    try {
      return this.normalizePathname(new URL(href, document.baseURI).pathname);
    } catch {
      return null;
    }
  }

  private normalizePathname(pathname: string): string {
    const pathOnly = pathname.split(/[?#]/, 1)[0] || "/";
    return pathOnly === "/" ? pathOnly : pathOnly.replace(/\/+$/, "");
  }

  private expandParentMenu(activeLink: HTMLAnchorElement): void {
    let parentCollapse = activeLink.closest<HTMLElement>(this.menuPanelSelector);
    while (parentCollapse) {
      parentCollapse.classList.add("show");
      parentCollapse.classList.remove("hidden");
      parentCollapse.hidden = false;
      const parentToggle = parentCollapse.previousElementSibling;
      if (parentToggle instanceof HTMLElement) {
        parentToggle.classList.add("active");
        parentToggle.setAttribute("aria-expanded", "true");
        parentToggle.closest<HTMLElement>(this.menuRootItemSelector)?.classList.add("active", "open");
      }
      parentCollapse = parentCollapse.parentElement?.closest<HTMLElement>(this.menuPanelSelector) ?? null;
    }
  }

  private bindDropdownViewportGuard(): void {
    this.on("mouseover", `${this.navSelector} > li.nav-item`, (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;

      const link = target.matches("a.nav-link") ? target : target.closest("a.nav-link");
      const dropdown = link?.nextElementSibling;
      if (!(link instanceof HTMLElement) || !(dropdown instanceof HTMLElement)) return;

      if (!this.elementInViewport(dropdown)) {
        dropdown.classList.add("dropdown-custom-right");
        dropdown.closest<HTMLElement>(".nav-item")?.classList.add("dropdown-custom-right");
        for (const child of dropdown.querySelectorAll<HTMLElement>(".menu-dropdown")) {
          child.classList.add("dropdown-custom-right");
        }
      } else if (window.innerWidth >= 1848) {
        for (const element of this.root.querySelectorAll<HTMLElement>(".dropdown-custom-right")) {
          element.classList.remove("dropdown-custom-right");
        }
      }
    });
  }

  private bindVerticalHoverToggle(): void {
    this.on("click", "#vertical-hover", (event) => {
      event.preventDefault();
      const html = document.documentElement;
      const current = html.getAttribute("data-sidebar-size");
      html.setAttribute("data-sidebar-size", current === "sm-hover" ? "sm-hover-active" : "sm-hover");
    });
  }

  private bindMainFrameNavigationState(): void {
    this.listen(document, "turbo:frame-render", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || !target.matches(this.mainFrameSelector)) return;

      this.activateCurrentSidebarItem();
      this.scrollActiveMenuIntoView();
    });
  }

  private scrollActiveMenuIntoView(): void {
    const wrapper = this.root.querySelector<HTMLElement>(this.scrollContainerSelector);
    const nav = this.root.querySelector<HTMLElement>(this.navSelector);
    // Group toggles are marked active too and precede their panel, so the
    // current page link is the last active anchor in document order.
    const activeLinks = nav ? Array.from(nav.querySelectorAll<HTMLElement>("a.active")) : [];
    const activeLink = activeLinks.at(-1) ?? null;
    if (!wrapper || !nav || !activeLink) return;
    const viewportHeight = wrapper.clientHeight;
    if (viewportHeight <= 0) return;

    // Keep the whole open group visible: its outermost item carries the parent
    // title, while the active link may sit further down inside a nested panel.
    const group = this.outermostMenuItem(activeLink, nav);
    const wrapperTop = wrapper.getBoundingClientRect().top - wrapper.scrollTop;
    const top = group.getBoundingClientRect().top - wrapperTop - SCROLL_INTO_VIEW_MARGIN;
    const bottom = activeLink.getBoundingClientRect().bottom - wrapperTop + SCROLL_INTO_VIEW_MARGIN;
    if (top >= wrapper.scrollTop && bottom <= wrapper.scrollTop + viewportHeight) return;

    // Show the parent title first; when the open group is taller than the
    // viewport the active link wins so the current page stays visible.
    wrapper.scrollTop = Math.max(0, top, bottom - viewportHeight);
  }

  private outermostMenuItem(link: HTMLElement, nav: HTMLElement): HTMLElement {
    let item = link.closest<HTMLElement>(this.menuRootItemSelector) ?? link;
    let candidate = item.parentElement?.closest<HTMLElement>(this.menuRootItemSelector) ?? null;
    while (candidate && nav.contains(candidate)) {
      item = candidate;
      candidate = candidate.parentElement?.closest<HTMLElement>(this.menuRootItemSelector) ?? null;
    }
    return item;
  }

  private elementInViewport(element: HTMLElement): boolean {
    const rect = element.getBoundingClientRect();
    return rect.top >= 0 && rect.left >= 0 && rect.bottom <= window.innerHeight && rect.right <= window.innerWidth;
  }
}
