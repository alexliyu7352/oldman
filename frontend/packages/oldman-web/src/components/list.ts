import { Component } from "../core/component/component";

const LIST_EMPTY_SELECTOR = "[data-om-list-empty]";
const LIST_ITEM_SELECTOR = "[data-om-list-item], .om-list > li, .list > li";
const LIST_PAGE_SELECTOR = "[data-om-list-page]";
const LIST_PAGINATION_SELECTOR = "[data-om-list-pagination], .om-list-pagination, .listjs-pagination";
const LIST_SEARCH_SELECTOR = "[data-om-list-search], .search, .fuzzy-search";
const LIST_SORT_SELECTOR = "[data-om-list-sort], .sort[data-sort]";

type ListSortDirection = "asc" | "desc";

interface ListSortState {
  direction: ListSortDirection;
  key: string;
}

/**
 * 为后端渲染列表提供无头搜索、模糊搜索、排序和本地分页能力。
 */
export class List extends Component {
  static readonly componentName = "list";
  private currentPage = 1;
  private sortState: ListSortState | null = null;

  /**
   * 绑定列表搜索、排序和分页控件，并同步初始可见状态。
   */
  override async mount(): Promise<void> {
    this.on("input", LIST_SEARCH_SELECTOR, () => {
      this.currentPage = 1;
      this.applyView();
    });

    this.on("click", LIST_SORT_SELECTOR, (event, target) => {
      event.preventDefault();
      this.setSort(target);
    });

    this.on("click", LIST_PAGE_SELECTOR, (event, target) => {
      event.preventDefault();
      const page = Number(target.getAttribute("data-om-list-page") || "1");
      if (!Number.isFinite(page) || page < 1) return;

      this.currentPage = page;
      this.applyView();
    });

    this.on("click", ".pagination-prev", (event) => {
      event.preventDefault();
      if (this.currentPage <= 1) return;
      this.currentPage -= 1;
      this.applyView();
    });

    this.on("click", ".pagination-next", (event) => {
      event.preventDefault();
      const pageCount = this.pageCount(this.filteredItems().length);
      if (this.currentPage >= pageCount) return;
      this.currentPage += 1;
      this.applyView();
    });

    this.applyView();
  }

  /**
   * 根据当前搜索、排序和分页状态刷新列表项可见性。
   */
  private applyView(): void {
    const items = this.items();
    const filteredItems = this.filteredItems();
    this.sortItems(filteredItems);

    const pageCount = this.pageCount(filteredItems.length);
    this.currentPage = Math.min(this.currentPage, pageCount);
    const pageSize = this.pageSize();
    const visibleItems = new Set(
      pageSize ? filteredItems.slice((this.currentPage - 1) * pageSize, this.currentPage * pageSize) : filteredItems
    );

    for (const item of items) {
      item.hidden = !visibleItems.has(item);
    }

    this.renderPagination(pageCount);
    this.renderEmptyState(filteredItems.length === 0);
  }

  /**
   * 返回当前搜索条件匹配的列表项。
   */
  private filteredItems(): HTMLElement[] {
    const query = this.searchInput()?.value.trim().toLocaleLowerCase() ?? "";
    const items = this.items();
    if (!query) return items;

    return items.filter((item) => this.matchesQuery(item, query));
  }

  /**
   * 判断列表项是否匹配普通搜索或模糊搜索。
   */
  private matchesQuery(item: HTMLElement, query: string): boolean {
    const text = (this.searchText(item) || item.textContent || "").toLocaleLowerCase();
    if (this.isFuzzySearch()) return this.fuzzyMatch(text, query);
    return text.includes(query);
  }

  /**
   * 返回用于搜索的列表项文本。
   */
  private searchText(item: HTMLElement): string {
    const selector = this.root.getAttribute("data-om-list-search-field");
    if (selector) return item.querySelector<HTMLElement>(selector)?.textContent?.trim() ?? "";
    return item.textContent?.trim() ?? "";
  }

  /**
   * 判断当前列表是否启用模糊搜索。
   */
  private isFuzzySearch(): boolean {
    return this.root.getAttribute("data-om-list-search-mode") === "fuzzy" || Boolean(this.root.querySelector(".fuzzy-search"));
  }

  /**
   * 执行轻量模糊匹配，要求查询字符按顺序出现在目标文本中。
   */
  private fuzzyMatch(text: string, query: string): boolean {
    let cursor = 0;
    for (const character of query) {
      cursor = text.indexOf(character, cursor);
      if (cursor === -1) return false;
      cursor += 1;
    }
    return true;
  }

  /**
   * 设置排序字段和方向。
   */
  private setSort(target: Element): void {
    const key = target.getAttribute("data-om-list-sort") || target.getAttribute("data-sort") || "";
    if (!key) return;

    const direction: ListSortDirection = this.sortState?.key === key && this.sortState.direction === "asc" ? "desc" : "asc";
    this.sortState = { direction, key };

    for (const sort of this.root.querySelectorAll<HTMLElement>(LIST_SORT_SELECTOR)) {
      sort.removeAttribute("aria-sort");
    }
    target.setAttribute("aria-sort", direction === "desc" ? "descending" : "ascending");
    this.applyView();
  }

  /**
   * 根据当前排序状态重排列表项 DOM。
   */
  private sortItems(items: HTMLElement[]): void {
    if (!this.sortState) return;

    items.sort((left, right) => {
      const leftValue = this.itemValue(left, this.sortState!.key);
      const rightValue = this.itemValue(right, this.sortState!.key);
      const result = leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });
      return this.sortState!.direction === "desc" ? -result : result;
    });

    const container = this.listContainer();
    if (!container) return;
    for (const item of items) {
      container.append(item);
    }
  }

  /**
   * 读取列表项中指定字段的排序值。
   */
  private itemValue(item: HTMLElement, key: string): string {
    const dataValue = item.getAttribute(`data-${key}`);
    if (dataValue !== null) return dataValue.trim();

    const field = item.querySelector<HTMLElement>(`.${key}`);
    if (field) {
      const timestamp = field.getAttribute("data-timestamp");
      if (timestamp !== null) return timestamp.trim();
      return field.textContent?.trim() ?? "";
    }

    return item.textContent?.trim() ?? "";
  }

  /**
   * 根据页数重建分页按钮，并同步上一页/下一页状态。
   */
  private renderPagination(pageCount: number): void {
    const pagination = this.root.querySelector<HTMLElement>(LIST_PAGINATION_SELECTOR);
    const prev = this.root.querySelector<HTMLElement>(".pagination-prev");
    const next = this.root.querySelector<HTMLElement>(".pagination-next");
    if (!pagination) return;

    pagination.replaceChildren();
    for (let page = 1; page <= pageCount; page += 1) {
      const item = document.createElement("li");
      item.className = "om-list-page-item";
      const link = document.createElement("a");
      link.className = `om-page-button${page === this.currentPage ? " is-active" : ""}`;
      // 这个 href 是占位符，不是地址：上面 `on("click", LIST_PAGE_SELECTOR)` 的委托处理器
      // 先 preventDefault，所以它从不执行；`<a>` 需要 href 才能被键盘聚焦，所以不能去掉。
      // `table.ts` 的 paginationButton() 用的是 <button>，那是更正确的形状；这里改过去会动到
      // 宿主针对 `.om-list-page-item a` 写的 CSS/JS，属于一次独立的、有意为之的 DOM 变更。
      link.href = "javascript:void(0);";
      link.dataset.omListPage = String(page);
      link.textContent = String(page);
      if (page === this.currentPage) {
        link.setAttribute("aria-current", "page");
      }
      item.append(link);
      pagination.append(item);
    }

    prev?.classList.toggle("disabled", this.currentPage <= 1);
    next?.classList.toggle("disabled", this.currentPage >= pageCount);
  }

  /**
   * 显示或隐藏空状态节点。
   */
  private renderEmptyState(empty: boolean): void {
    const emptyElement = this.root.querySelector<HTMLElement>(LIST_EMPTY_SELECTOR);
    if (!emptyElement) return;

    emptyElement.hidden = !empty;
  }

  /**
   * 返回当前列表总页数。
   */
  private pageCount(totalItems: number): number {
    const pageSize = this.pageSize();
    return pageSize ? Math.max(1, Math.ceil(totalItems / pageSize)) : 1;
  }

  /**
   * 读取本地分页大小；未配置时不分页。
   */
  private pageSize(): number | null {
    const rawValue = this.root.getAttribute("data-om-list-page-size");
    if (!rawValue) return null;

    const parsed = Number(rawValue);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  /**
   * 返回搜索输入框。
   */
  private searchInput(): HTMLInputElement | null {
    return this.root.querySelector<HTMLInputElement>(LIST_SEARCH_SELECTOR);
  }

  /**
   * 返回列表项容器。
   */
  private listContainer(): HTMLElement | null {
    return this.root.querySelector<HTMLElement>("[data-om-list-items], .list");
  }

  /**
   * 返回当前组件管理的列表项。
   */
  private items(): HTMLElement[] {
    return Array.from(this.root.querySelectorAll<HTMLElement>(LIST_ITEM_SELECTOR));
  }
}
