import { cssEscape } from "../core/dom/helpers";
import { relativeUrl } from "../core/http/urls";
import { Component } from "../core/component/component";
import { isCanceledError } from "../core/services/abort";
import { queryAllSelfOrDescendants } from "../core/dom/helpers";
import { ScopedPreloader } from "../core/services/preloader";
import { createPreferenceStore, type PreferenceStore } from "../core/services/preferences";
import { Dropdown } from "./dropdown";
import type { JsonTableModel, TableJsonPayload, TableJsonRow } from "./table-json";

const TABLE_EMPTY_SELECTOR = "[data-om-table-empty]";
const TABLE_ERROR_SELECTOR = "[data-om-table-error]";
const TABLE_FILTER_SELECTOR = "[data-om-table-filter]";
const TABLE_LOADING_SELECTOR = "[data-om-table-loading]";
const TABLE_PAGE_SELECTOR = "[data-om-table-page]";
const TABLE_PAGE_SIZE_CONTROL_SELECTOR = "[data-om-table-page-size-control]";
const TABLE_PAGINATION_SELECTOR = "[data-om-table-pagination]";
const TABLE_PARTIAL_SELECTOR = "[data-om-table-partial]";
const TABLE_INITIAL_SELECTOR = "[data-om-initial-table-partial]";
const TABLE_INITIAL_LOADING_SELECTOR = "[data-om-table-initial-loading]";
const TABLE_BODY_SELECTOR = "[data-om-table-body]";
const TABLE_ROW_SELECTOR = "[data-om-table-row]";
const TABLE_SELECT_ALL_SELECTOR = "[data-om-table-select-all]";
const TABLE_SELECT_ROW_SELECTOR = "[data-om-table-select-row]";
const TABLE_SHELL_SELECTOR = ".om-table-shell";
const TABLE_SCROLL_SELECTOR = ".om-table-scroll";
const TABLE_SCROLL_FIT_CLASS = "is-fit";
const TABLE_SORT_SELECTOR = "[data-om-table-sort]";
const TABLE_SUMMARY_SELECTOR = "[data-om-table-summary]";
const TABLE_SELECTION_COUNT_SELECTOR = "[data-om-table-selection-count]";
const TABLE_BULK_ACTIONS_SELECTOR = "[data-om-table-bulk-actions]";
const TABLE_COLUMN_TOGGLE_SELECTOR = "[data-om-table-column-toggle]";
const TABLE_DENSITY_SELECTOR = "[data-om-table-density]";
// State attribute on the component root. Never reuse a trigger attribute here: delegated handlers
// match the closest ancestor, and the root is one of them, so a shared name would swallow every click.
const TABLE_DENSITY_STATE_ATTRIBUTE = "data-om-density";
const TABLE_EXPORT_SELECTOR = "[data-om-table-export]";
const TABLE_EMPTY_RESET_SELECTOR = "[data-om-table-empty-reset]";
const TABLE_EMPTY_TEMPLATE_SELECTOR = "template[data-om-table-empty-template]";
const TABLE_COLUMN_CELL_SELECTOR = "th[data-om-column], td[data-om-column]";

export interface TableRefreshDetail<TTable extends Table = Table> {
  component: TTable;
  format: "html" | "json";
  url: string;
}

export interface TableRefreshErrorDetail<TTable extends Table = Table> {
  component: TTable;
  error: unknown;
  message: string;
  url: string;
}

export interface TableSelectionDetail<TTable extends Table = Table> {
  component: TTable;
  ids: string[];
}

export type TableStatus = "idle" | "loading" | "success" | "error";
export type TableDensity = "comfortable" | "compact";
type TableSortDirection = "ascending" | "descending";

/** Per-table view choices remembered in the browser (toolbar "Columns" and "Density"). */
interface TableViewPreferences {
  density?: TableDensity;
  hiddenColumns?: string[];
}

interface TableSortState {
  direction: TableSortDirection;
  key: string;
}

interface TableColumnMetadata {
  name: string;
  searchable: boolean;
  sortable: boolean;
  type: string;
}

/**
 * 为后端渲染表格提供无头过滤、分页状态和 HTML 片段刷新能力。
 */
/** Whether one table request carries state: a query, a page, a sort or any filter. */
function describesTableState(url: URL): boolean {
  if (["q", "page", "sort"].some((name) => url.searchParams.get(name))) return true;
  return Array.from(url.searchParams.keys()).some((name) => name.startsWith("filter."));
}

/** The same question for a page URL, where filters appear under their bare names. */
function pageDescribesTableState(url: URL, filterNames: Set<string>): boolean {
  if (describesTableState(url)) return true;
  return Array.from(filterNames).some((name) => {
    const normalized = name.startsWith("filter.") ? name.slice("filter.".length) : name;
    return Boolean(url.searchParams.get(normalized));
  });
}

export class Table extends Component {
  static readonly componentName = "table";
  private currentPage = 1;
  private externalFormParams: URLSearchParams | null = null;
  private externalFormFieldNames = new Set<string>();
  /** Filter names removed by resetFilters(); the next page-URL sync must still delete their parameters. */
  private clearedFilterNames = new Set<string>();
  private loadingPreloader: ScopedPreloader | null = null;
  private loadingPreloaderRoot: HTMLElement | null = null;
  private jsonTableModel: JsonTableModel | null = null;
  private refreshCommitQueue = Promise.resolve();
  private refreshSerial = 0;
  private searchInteracted = false;
  private sortState: TableSortState | null = null;
  private fallbackPreferences: PreferenceStore | null = null;
  private hiddenColumns = new Set<string>();
  private density: TableDensity = "comfortable";
  private lastSelectionKey = "";
  private fitObserver: ResizeObserver | null = null;
  private fitObserverTarget: HTMLElement | null = null;
  private fitUpdate: (() => void) | null = null;

  /**
   * 绑定表格控件，并同步初始可见行状态。
   */
  override async mount(): Promise<void> {
    this.manager?.register("dropdown", Dropdown);
    if (this.isJsonMode() && !this.remoteSource()) {
      throw new Error("JSON tables require data-om-table-src");
    }

    this.listen(this.root, "om:table:reload", () => {
      void this.reload();
    });

    this.on("input", TABLE_FILTER_SELECTOR, () => {
      this.searchInteracted = true;
      if (this.isServerMode()) {
        this.currentPage = 1;
        void this.refresh();
        return;
      }

      this.currentPage = 1;
      this.applyLocalView();
    });

    this.on("click", TABLE_PAGE_SELECTOR, (event, target) => {
      event.preventDefault();
      if (!(target instanceof HTMLElement)) return;

      if (this.isServerMode()) {
        this.currentPage = this.pageFromTarget(target);
        void this.refresh(this.buildUrl(target));
        return;
      }

      this.setActivePage(target);
    });

    this.on("change", TABLE_PAGE_SIZE_CONTROL_SELECTOR, () => {
      this.currentPage = 1;
      if (this.isServerMode()) {
        void this.refresh(this.buildUrl(undefined, { page: 1 }));
        return;
      }

      this.applyLocalView();
    });

    this.on("click", TABLE_SORT_SELECTOR, (event, target) => {
      event.preventDefault();
      if (!(target instanceof HTMLElement)) return;

      if (this.isServerMode()) {
        this.setRemoteSort(target);
        void this.refresh(this.buildUrl(target));
        return;
      }

      this.setLocalSort(target);
    });

    this.on("change", TABLE_SELECT_ALL_SELECTOR, (_event, target) => {
      if (!(target instanceof HTMLInputElement)) return;
      this.jsonTableModel?.setAllRowsSelected(target.checked);
      this.setVisibleRowsSelected(target.checked);
    });

    this.on("change", TABLE_SELECT_ROW_SELECTOR, (_event, target) => {
      if (target instanceof HTMLInputElement && this.jsonTableModel) {
        this.jsonTableModel.setRowSelected(target.value, target.checked);
      }
      this.syncSelectionState();
    });

    this.on("change", TABLE_COLUMN_TOGGLE_SELECTOR, (_event, target) => {
      if (!(target instanceof HTMLInputElement)) return;
      this.setColumnHidden(target.value, !target.checked);
    });

    this.on("click", TABLE_DENSITY_SELECTOR, (event, target) => {
      event.preventDefault();
      if (!(target instanceof HTMLElement)) return;
      this.setDensity(target.getAttribute("data-om-table-density") === "compact" ? "compact" : "comfortable");
    });

    this.on("click", TABLE_EXPORT_SELECTOR, (event, target) => {
      event.preventDefault();
      if (!(target instanceof HTMLElement)) return;
      const format = target.getAttribute("data-om-table-export") || "";
      if (format) this.download(this.exportUrl(format));
    });

    this.on("click", TABLE_EMPTY_RESET_SELECTOR, (event) => {
      event.preventDefault();
      void this.resetFilters();
    });

    this.restoreViewPreferences();
    this.observeScrollFit();
    this.cleanup(() => this.fitObserver?.disconnect());

    if (this.isServerMode()) {
      if (this.syncsPageUrl()) this.restoreInitialPageState();
      this.restoreInitialSortState();
      this.syncSelectionState();
      if (this.partialNeedsInitialRefresh()) {
        void this.refresh().catch((error: unknown) => {
          this.logger.error("Oldman table initial refresh failed", error);
        });
      }
      return;
    }

    this.applyLocalView();
  }

  /** Reload the current table mode and resolve after its visible state is updated. */
  async reload(): Promise<void> {
    if (this.isServerMode()) {
      await this.refresh();
      return;
    }
    this.applyLocalView();
  }

  /**
   * 从后端加载当前远程格式并更新表格局部区域。
   */
  async refresh(url = this.buildUrl()): Promise<void> {
    const refreshSerial = ++this.refreshSerial;
    const format = this.dataFormat();
    this.setStatus("loading", this.i18n.t("Loading..."));
    this.showLoading();
    // 地址栏与根节点状态只依赖请求本身，等响应回来再写就晚了：用户在这一来一回之间点了
    // "新增"，Turbo 会先缓存快照再换页，这一页的筛选、排序、页码就一起丢了，取消返回时
    // 看到的是一张默认表格。
    if (this.isServerMode() && this.syncsPageUrl()) this.syncPageUrl(url);

    try {
      if (format === "json") {
        const [adapter, payload] = await Promise.all([
          import("./table-json"),
          this.http.getJson<unknown>(url)
        ]);
        if (!this.isCurrentRefresh(refreshSerial)) return;
        await this.enqueueRefreshCommit(refreshSerial, () => this.replaceJsonPayload(adapter, payload, url));
      } else {
        const html = await this.http.html(url);
        if (!this.isCurrentRefresh(refreshSerial)) return;
        await this.enqueueRefreshCommit(refreshSerial, () => this.replacePartial(html));
      }

      // 服务端模式下搜索、排序、分页可能连续触发，只允许最新响应改写 DOM。
      if (!this.isCurrentRefresh(refreshSerial)) return;

      this.setStatus("success");
      if (this.isServerMode()) {
        if (this.sortState) this.syncSortControls();
        this.syncSelectionState();
        this.applyColumnVisibility();
        this.observeScrollFit();
      } else {
        this.applyLocalView();
      }
      this.emit<TableRefreshDetail>("om:table:refresh", { component: this, format, url });
    } catch (error) {
      if (this.isCanceledRefresh(error)) return;

      // 旧请求失败时不覆盖较新请求的成功状态，也避免事件回调产生无意义的未处理异常。
      if (!this.isCurrentRefresh(refreshSerial)) return;

      const message = this.errorMessage(error);
      this.setStatus("error", message);
      this.emit<TableRefreshErrorDetail>("om:table:error", { component: this, error, message, url });
      throw error;
    } finally {
      if (this.isCurrentRefresh(refreshSerial)) {
        this.hideLoading();
      }
    }
  }

  /**
   * 表格刷新时只覆盖数据阅读区域；首屏空壳没有表格结构时回退到组件根。
   */
  private showLoading(): void {
    this.setInitialLoadingRowsHidden(true);
    const preloader = this.preloaderForLoadingScope();
    preloader.show(this.i18n.t("Loading..."));
  }

  private hideLoading(): void {
    this.loadingPreloader?.hide();
  }

  private setInitialLoadingRowsHidden(hidden: boolean): void {
    for (const row of this.root.querySelectorAll<HTMLElement>(TABLE_INITIAL_LOADING_SELECTOR)) {
      row.style.visibility = hidden ? "hidden" : "";
      if (hidden) {
        row.setAttribute("aria-hidden", "true");
      } else {
        row.removeAttribute("aria-hidden");
      }
    }
  }

  private preloaderForLoadingScope(): ScopedPreloader {
    const root = this.loadingScope();
    if (this.loadingPreloader && this.loadingPreloaderRoot === root) {
      return this.loadingPreloader;
    }

    this.loadingPreloader?.hide();
    this.loadingPreloaderRoot = root;
    this.loadingPreloader = new ScopedPreloader(root, this.cleanupRegistry, this.i18n);
    return this.loadingPreloader;
  }

  private loadingScope(): HTMLElement {
    const shell = this.root.querySelector<HTMLElement>(TABLE_SHELL_SELECTOR);
    if (shell) return shell;
    return this.partialContainer() ?? this.root;
  }

  /**
   * 应用外部筛选表单。调用方负责处理表单 submit，Table 只负责把筛选转换为自身刷新请求。
   */
  async applyFilterForm(form: HTMLFormElement): Promise<void> {
    this.currentPage = 1;
    this.externalFormFieldNames = new Set(
      Array.from(new FormData(form).keys(), (name) => String(name)).filter((name) => name !== "q")
    );
    this.externalFormParams = this.formTableParams(form);
    if (this.isServerMode()) {
      await this.refresh(this.buildUrl(undefined, { page: 1 }));
      return;
    }
    this.applyLocalView();
  }

  /**
   * 判断刷新是否被页面卸载或新请求主动取消，取消不属于业务错误。
   */
  private isCanceledRefresh(error: unknown): boolean {
    return this.signal.aborted || isCanceledError(error);
  }

  /**
   * 根据当前过滤、排序和分页状态刷新本地行可见性。
   */
  private applyLocalView(): void {
    const filter = this.root.querySelector<HTMLInputElement>(TABLE_FILTER_SELECTOR);
    const empty = this.root.querySelector<HTMLElement>(TABLE_EMPTY_SELECTOR);
    const query = filter?.value.trim().toLocaleLowerCase() ?? "";
    const rows = this.localRows();
    const filteredRows = rows.filter((row) => this.rowMatchesQuery(row, query));

    this.sortRows(filteredRows);

    const pageSize = this.pageSize();
    const pageCount = pageSize ? Math.max(1, Math.ceil(filteredRows.length / pageSize)) : 1;
    this.currentPage = Math.min(this.currentPage, pageCount);
    const pageRows = pageSize ? filteredRows.slice((this.currentPage - 1) * pageSize, this.currentPage * pageSize) : filteredRows;
    const visibleRows = new Set(pageRows);

    for (const row of rows) {
      row.hidden = !visibleRows.has(row);
    }

    this.renderPagination(pageCount);
    this.renderSummary(filteredRows.length, pageRows.length);
    this.syncSelectionState();

    if (!empty) return;

    empty.textContent = this.i18n.t("No matching records");
    empty.hidden = filteredRows.length > 0;
  }

  /**
   * 标记当前分页控件为激活状态，视觉样式交给项目侧处理。
   */
  private setActivePage(target: HTMLElement): void {
    const rawPage = Number(target.getAttribute("data-om-table-page") || "1");
    this.currentPage = Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1;

    for (const page of this.root.querySelectorAll<HTMLElement>(TABLE_PAGE_SELECTOR)) {
      const isActive = page === target;
      page.classList.toggle("active", isActive);

      if (isActive) {
        page.setAttribute("aria-current", "page");
        continue;
      }

      page.removeAttribute("aria-current");
    }

    this.applyLocalView();
  }

  /**
   * 更新表格加载状态，并同步可选状态元素。
   */
  private setStatus(status: TableStatus, message = ""): void {
    this.root.dataset.omStatus = status;

    const loading = this.root.querySelector<HTMLElement>(TABLE_LOADING_SELECTOR);
    if (loading) {
      loading.textContent = status === "loading" ? message : "";
      loading.hidden = true;
    }

    const error = this.root.querySelector<HTMLElement>(TABLE_ERROR_SELECTOR);
    if (error) {
      error.textContent = status === "error" ? message : "";
      error.hidden = status !== "error";
    }
  }

  /**
   * 生成远程刷新 URL，并合并搜索、分页、排序参数。
   */
  private buildUrl(trigger?: HTMLElement, overrides: { page?: number } = {}): string {
    const base = trigger?.getAttribute("data-om-table-url") || trigger?.getAttribute("href") || this.remoteSource() || window.location.href;
    const url = new URL(base, window.location.href);
    const filter = this.root.querySelector<HTMLInputElement>(TABLE_FILTER_SELECTOR);

    if (this.externalFormParams) {
      this.appendExternalFormParams(url);
    } else {
      this.appendInitialFilters(url);
    }

    if (filter?.value.trim()) {
      url.searchParams.set(filter.getAttribute("data-om-table-param") || "q", filter.value.trim());
    } else if (!this.externalFormParams && !this.searchInteracted && this.initialQuery()) {
      url.searchParams.set("q", this.initialQuery()!);
    }

    const pageSize = this.pageSize();
    if (pageSize) {
      url.searchParams.set("page_size", String(pageSize));
    }

    const page = overrides.page ?? (trigger?.matches(TABLE_PAGE_SELECTOR) ? this.pageFromTarget(trigger) : this.currentPage);
    if (page > 1 || overrides.page !== undefined || trigger?.matches(TABLE_PAGE_SELECTOR)) {
      url.searchParams.set("page", String(page));
    }

    const initialSort = this.initialSort();
    if (this.sortState) {
      const sortKey = this.sortState.direction === "descending" ? `-${this.sortState.key}` : this.sortState.key;
      url.searchParams.set("sort", sortKey);
    } else if (initialSort) {
      url.searchParams.set("sort", initialSort);
    }

    return relativeUrl(url);
  }

  /**
   * 读取后端 shell 注入的初始排序，只在用户尚未交互排序时使用。
   */
  private initialSort(): string | null {
    const value = this.root.getAttribute("data-om-table-initial-sort")?.trim() || "";
    return value.length > 0 ? value : null;
  }

  /** Restore a directly addressed page before the first remote request. */
  private restoreInitialPageState(): void {
    const value = Number(this.root.getAttribute("data-om-table-initial-page") || "1");
    this.currentPage = Number.isFinite(value) && value > 0 ? value : 1;
  }

  /** URL state is an explicit consumer opt-in so existing Dashboard tables keep source behavior. */
  private syncsPageUrl(): boolean {
    return this.root.getAttribute("data-om-table-sync-url") === "true";
  }

  /**
   * Keep the browser page URL in step with remote table state without exposing
   * the table data endpoint path or discarding Turbo's restoration metadata.
   */
  private syncPageUrl(requestUrl: string): void {
    const request = new URL(requestUrl, window.location.href);
    const page = new URL(window.location.href);
    const initialFilterNames = Array.from(this.root.attributes)
      .filter((attribute) => attribute.name.startsWith("data-om-filter-"))
      .map((attribute) => attribute.name.replace("data-om-filter-", "").replaceAll("-", "_"));
    const filterNames = new Set([...initialFilterNames, ...this.externalFormFieldNames, ...this.clearedFilterNames]);
    // 用户清空搜索或筛选时，请求里同样没有状态，但那是一次真实操作，地址栏必须跟着清干净。
    // 要跳过的只有"组件自己还不知道状态"的那一次刷新：Turbo 还原之后组件可能先于服务端注入的
    // data-om-* 状态挂载完成，于是按默认值请求一次。`replaceState` 改的是历史条目本身，一旦让它
    // 抹掉，用户按"取消/后退"回来的就是一个没有筛选的列表。
    const userDrivenRefresh = Boolean(
      this.externalFormParams
      || this.searchInteracted
      || this.sortState
      || this.clearedFilterNames.size
      || filterNames.size
      || this.initialQuery()
      || this.initialSort()
    );
    if (!userDrivenRefresh && !describesTableState(request) && pageDescribesTableState(page, filterNames)) return;
    this.clearedFilterNames = new Set();
    for (const name of ["q", "page_size", "page", "sort"]) {
      const wasExplicit = page.searchParams.has(name);
      page.searchParams.delete(name);
      const value = request.searchParams.get(name);
      if (!value) continue;
      if (name === "page_size" && !wasExplicit && value === this.defaultPageSize()) continue;
      page.searchParams.set(name, value);
    }

    for (const name of filterNames) {
      page.searchParams.delete(name.startsWith("filter.") ? name.slice("filter.".length) : name);
    }
    for (const [name, value] of request.searchParams.entries()) {
      if (!name.startsWith("filter.")) continue;
      page.searchParams.set(name.slice("filter.".length), value);
    }

    this.syncRootUrlState(request, filterNames);
    const nextUrl = `${page.pathname}${page.search}${page.hash}`;
    window.history.replaceState(window.history.state, "", nextUrl);
  }

  /** Persist synchronized state on the Turbo-cached shell for the next Table instance. */
  private syncRootUrlState(request: URL, filterNames: Set<string>): void {
    this.syncRootAttribute("data-om-table-initial-query", request.searchParams.get("q"));
    this.syncRootAttribute("data-om-table-page-size", request.searchParams.get("page_size"));
    this.syncRootAttribute("data-om-table-initial-page", request.searchParams.get("page"));
    this.syncRootAttribute("data-om-table-initial-sort", request.searchParams.get("sort"));

    for (const name of filterNames) {
      const normalizedName = name.startsWith("filter.") ? name.slice("filter.".length) : name;
      this.root.removeAttribute(`data-om-filter-${normalizedName.replaceAll("_", "-")}`);
    }
    for (const [name, value] of request.searchParams.entries()) {
      if (!name.startsWith("filter.")) continue;
      const normalizedName = name.slice("filter.".length);
      this.root.setAttribute(`data-om-filter-${normalizedName.replaceAll("_", "-")}`, value);
    }
  }

  private syncRootAttribute(name: string, value: string | null): void {
    if (value) {
      this.root.setAttribute(name, value);
      return;
    }
    this.root.removeAttribute(name);
  }

  /** Return the server-side default used when the page URL omits page_size. */
  private defaultPageSize(): string | null {
    const value = this.root.getAttribute("data-om-table-default-page-size")?.trim();
    return value ? value : null;
  }

  /**
   * 将服务端 shell 中的 URL 排序状态恢复到交互控件，确保 Turbo 历史后退后数据与 aria 状态一致。
   */
  private restoreInitialSortState(): void {
    const value = this.initialSort();
    if (!value) return;
    const key = value.startsWith("-") ? value.slice(1) : value;
    if (!key) return;
    this.sortState = {
      direction: value.startsWith("-") ? "descending" : "ascending",
      key,
    };
    this.syncSortControls();
  }

  /**
   * 从分页控件读取页码。
   */
  private pageFromTarget(target: HTMLElement): number {
    const rawPage = Number(target.getAttribute("data-om-table-page") || "1");
    return Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1;
  }

  /**
   * 读取后端 shell 注入的初始搜索词，供没有内置搜索框的筛选表单页面首刷使用。
   */
  private initialQuery(): string | null {
    const value = this.root.getAttribute("data-om-table-initial-query")?.trim() || "";
    return value.length > 0 ? value : null;
  }

  /**
   * 把后端 shell 输出的初始可见筛选转换为正式 filter.<name> 请求参数。
   */
  private appendInitialFilters(url: URL): void {
    for (const attr of Array.from(this.root.attributes)) {
      if (!attr.name.startsWith("data-om-filter-")) continue;
      if (!attr.value.trim()) continue;

      const filterName = attr.name.replace("data-om-filter-", "").replaceAll("-", "_");
      url.searchParams.set(`filter.${filterName}`, attr.value);
    }
  }

  /**
   * 把外部筛选表单转换后的参数附加到远程 Table 请求。
   */
  private appendExternalFormParams(url: URL): void {
    if (!this.externalFormParams) return;
    for (const [key, value] of this.externalFormParams.entries()) {
      url.searchParams.set(key, value);
    }
  }

  /**
   * 将外部筛选表单字段转换为 Table 正式请求参数。
   */
  private formTableParams(form: HTMLFormElement): URLSearchParams {
    const params = new URLSearchParams();
    const data = new FormData(form);
    for (const [name, value] of data.entries()) {
      if (typeof value !== "string") continue;
      const normalized = value.trim();
      if (!normalized) continue;
      const paramName = name === "q" || name.startsWith("filter.") ? name : `filter.${name}`;
      params.set(paramName, normalized);
    }
    return params;
  }

  /** 校验并渲染当前服务器页的 JSON 数据。 */
  private async replaceJsonPayload(adapter: typeof import("./table-json"), value: unknown, requestUrl: string): Promise<void> {
    const expectedColumns = Array.from(this.localColumnMetadata().keys());
    const selectable = Boolean(this.root.querySelector(TABLE_SELECT_ALL_SELECTOR));
    const payload = adapter.parseTableJsonPayload(value, expectedColumns);
    const body = this.root.querySelector<HTMLTableSectionElement>(TABLE_BODY_SELECTOR);
    const partial = this.partialContainer();
    const pageSizeControl = this.root.querySelector<HTMLSelectElement | HTMLInputElement>(TABLE_PAGE_SIZE_CONTROL_SELECTOR);
    if (!body || !partial || !pageSizeControl || !this.root.querySelector(TABLE_SUMMARY_SELECTOR) || !this.root.querySelector(TABLE_PAGINATION_SELECTOR)) {
      throw new Error("JSON table shell is missing required regions");
    }

    this.jsonTableModel ??= new adapter.JsonTableModel();
    const rows = this.jsonTableModel.update(
      payload,
      {
        page: payload.pagination.page,
        pageSize: payload.pagination.page_size,
        search: new URL(requestUrl, window.location.href).searchParams.get("q") || "",
        sort: this.jsonSortState(payload.sort)
      },
      selectable
    );

    if (this.manager) await this.unmountDynamicComponents(body);
    body.replaceChildren(this.renderJsonRows(payload, rows, selectable));
    this.clearInitialPartialState(partial);
    this.currentPage = payload.pagination.page;
    pageSizeControl.value = String(payload.pagination.page_size);
    this.renderSummary(payload.pagination.filtered_total, rows.length);
    this.renderPagination(Math.max(1, Math.ceil(payload.pagination.filtered_total / payload.pagination.page_size)), true);
    if (this.manager) await this.mountDynamicComponents(body);
  }

  /** 按现有 Oldman DOM 协议生成 JSON 行。 */
  private renderJsonRows(payload: TableJsonPayload, rows: readonly TableJsonRow[], selectable: boolean): DocumentFragment {
    const fragment = document.createDocumentFragment();
    if (rows.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = payload.columns.length + (selectable ? 1 : 0);
      cell.className = "om-table-empty-cell";
      // The shell ships both empty-state variants as templates; "filtered" when the user's filters hid records.
      const variant = payload.pagination.filtered_total < payload.pagination.total ? "filtered" : "all";
      const template = this.root.querySelector<HTMLTemplateElement>(`${TABLE_EMPTY_TEMPLATE_SELECTOR}[data-om-table-empty-template="${variant}"]`);
      if (template) cell.append(template.content.cloneNode(true));
      else cell.textContent = this.root.getAttribute("data-om-table-empty-message") || "";
      row.append(cell);
      fragment.append(row);
      return fragment;
    }

    for (const payloadRow of rows) {
      const row = document.createElement("tr");
      row.setAttribute("data-om-table-row", "");
      row.setAttribute("data-om-table-row-id", String(payloadRow.data.id));
      if (selectable) row.append(this.renderJsonSelectionCell(payloadRow));

      for (const column of payload.columns) {
        const cell = document.createElement("td");
        const rawValue = payloadRow.raw_values[column.name];
        cell.setAttribute("data-om-column", column.name);
        cell.setAttribute("data-om-column-label", column.label);
        cell.setAttribute("data-raw-value", rawValue === null ? "" : String(rawValue));
        cell.innerHTML = payloadRow.cells[column.name] ?? "";
        row.append(cell);
      }
      fragment.append(row);
    }
    return fragment;
  }

  private renderJsonSelectionCell(row: TableJsonRow): HTMLTableCellElement {
    const cell = document.createElement("td");
    const label = this.root.querySelector<HTMLElement>("th[data-om-column-selection]")?.getAttribute("data-om-column-label") || "";
    cell.setAttribute("data-om-column-selection", "");
    cell.setAttribute("data-om-column-label", label);
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "om-check";
    checkbox.setAttribute("data-om-table-select-row", "");
    checkbox.setAttribute("aria-label", `${label} ${String(row.data.id)}`.trim());
    checkbox.value = String(row.data.id);
    cell.append(checkbox);
    return cell;
  }

  private jsonSortState(sort: string): { descending: boolean; key: string } | null {
    if (this.sortState) {
      return { descending: this.sortState.direction === "descending", key: this.sortState.key };
    }
    const key = sort.startsWith("-") ? sort.slice(1) : sort;
    return key ? { descending: sort.startsWith("-"), key } : null;
  }

  /**
   * 用后端返回片段替换当前表格局部区域。
   */
  private async replacePartial(html: string): Promise<void> {
    const target = this.partialContainer();
    if (!target) return;
    const wasInitialPartial = target.hasAttribute("data-om-initial-table-partial");
    this.clearInitialPartialState(target);

    const template = document.createElement("template");
    template.innerHTML = html.trim();
    const remotePartial = template.content.querySelector<HTMLElement>(TABLE_PARTIAL_SELECTOR);

    if (remotePartial) {
      if (!wasInitialPartial && await this.replacePartialRegions(target, remotePartial)) {
        this.clearInitialPartialState(target);
        return;
      }

      await this.replaceContainerHtml(target, remotePartial.innerHTML);
      this.clearInitialPartialState(target);
      return;
    }

    await this.replaceContainerHtml(target, html);
    this.clearInitialPartialState(target);
  }

  private clearInitialPartialState(target: HTMLElement): void {
    target.removeAttribute("data-om-initial-table-partial");
  }

  /**
   * 服务端通常返回完整表格片段；已有表格只替换会变化的区域，避免表头状态和宽度抖动。
   */
  private async replacePartialRegions(target: HTMLElement, remotePartial: HTMLElement): Promise<boolean> {
    if (target === this.root) return false;

    let replaced = false;
    replaced = (await this.replaceRegion(target, remotePartial, TABLE_BODY_SELECTOR, "tbody")) || replaced;
    replaced = (await this.replaceRegion(target, remotePartial, TABLE_SUMMARY_SELECTOR)) || replaced;
    replaced = (await this.replaceRegion(target, remotePartial, TABLE_PAGINATION_SELECTOR)) || replaced;
    return replaced;
  }

  /**
   * 替换一个可独立刷新的表格区域；缺少目标区域时交给整块替换兜底。
   */
  private async replaceRegion(target: HTMLElement, remotePartial: HTMLElement, selector: string, fallbackSelector?: string): Promise<boolean> {
    const targetRegion = target.querySelector<HTMLElement>(selector) ?? (fallbackSelector ? target.querySelector<HTMLElement>(fallbackSelector) : null);
    const remoteRegion = remotePartial.querySelector<HTMLElement>(selector) ?? (fallbackSelector ? remotePartial.querySelector<HTMLElement>(fallbackSelector) : null);
    if (!targetRegion || !remoteRegion) return false;

    const nextRegion = remoteRegion.cloneNode(true) as HTMLElement;
    if (this.manager) await this.unmountDynamicComponents(targetRegion);
    targetRegion.replaceWith(nextRegion);
    if (this.manager) await this.mountDynamicComponents(nextRegion);
    return true;
  }

  /**
   * 整块替换表格局部内容，并维护其中声明式子组件的生命周期。
   */
  private async replaceContainerHtml(target: HTMLElement, html: string): Promise<void> {
    if (this.manager) await this.unmountDynamicComponents(target);
    target.innerHTML = html;
    if (this.manager) await this.mountDynamicComponents(target);
  }

  /**
   * 挂载远程 HTML 片段里新插入的声明式组件。
   */
  private async mountDynamicComponents(root: HTMLElement): Promise<void> {
    if (!this.manager) return;

    this.decorateDropdowns(root);

    const candidates: HTMLElement[] = [];
    if (root.matches("[data-om-component]")) candidates.push(root);
    candidates.push(...Array.from(root.querySelectorAll<HTMLElement>("[data-om-component]")));

    for (const element of candidates) {
      if (element === this.root) continue;
      const parent = element.parentElement?.closest<HTMLElement>("[data-om-component]") ?? null;
      if (parent && parent !== this.root && root.contains(parent)) continue;
      await this.manager.mount(element);
    }
  }

  /**
   * 服务端表格片段刷新后接入 Oldman Dropdown。
   */
  private decorateDropdowns(root: ParentNode): void {
    for (const element of queryAllSelfOrDescendants<HTMLElement>(root, ".om-dropdown, [data-om-component='dropdown']")) {
      const toggle = element.querySelector<HTMLElement>("[data-om-dropdown-toggle]");
      const menu = element.querySelector<HTMLElement>(".om-dropdown-menu, [data-om-dropdown-menu]");
      if (!toggle || !menu) continue;

      element.dataset.omComponent = "dropdown";
      toggle.dataset.omDropdownToggle = "";
      menu.dataset.omDropdownMenu = "";

      if (!menu.classList.contains("show")) {
        menu.classList.add("hidden");
        menu.hidden = true;
      }
    }
  }

  /**
   * 在 DOM 替换前卸载将被移除的声明式组件，避免事件和状态残留。
   */
  private async unmountDynamicComponents(root: HTMLElement): Promise<void> {
    await this.manager?.unmount(root);
  }

  /**
   * 判断当前远程刷新是否仍然是最新请求。
   */
  private isCurrentRefresh(refreshSerial: number): boolean {
    // 组件卸载后这次刷新就不再有"当前"可言：响应可能正好赶在 abort 之前落地，继续往下走
    // 会把 DOM、状态、以及 syncPageUrl 的 replaceState 写到已经属于下一个页面的历史条目上。
    return refreshSerial === this.refreshSerial && !this.signal.aborted;
  }

  /** 串行执行异步 DOM 生命周期；单次异常仍交给对应 refresh，后续提交可以继续。 */
  private enqueueRefreshCommit(refreshSerial: number, commit: () => Promise<void>): Promise<void> {
    const queued = this.refreshCommitQueue.then(async () => {
      if (this.isCurrentRefresh(refreshSerial)) await commit();
    });
    this.refreshCommitQueue = queued.catch(() => {});
    return queued;
  }

  /**
   * 返回当前表格需要替换的 HTML 片段容器。
   */
  private partialContainer(): HTMLElement | null {
    if (this.root.matches(TABLE_PARTIAL_SELECTOR)) return this.root;
    return this.root.querySelector<HTMLElement>(TABLE_PARTIAL_SELECTOR);
  }

  /**
   * 判断服务端表格 shell 是否还没有任何可显示内容。
   */
  private partialIsEmpty(): boolean {
    const partial = this.partialContainer();
    return !partial || partial.children.length === 0 && partial.textContent?.trim() === "";
  }

  /**
   * 首屏远程表格可能已渲染静态表头和 loading 行，但仍需请求真实数据。
   */
  private partialNeedsInitialRefresh(): boolean {
    return this.partialIsEmpty() || Boolean(this.root.querySelector(TABLE_INITIAL_SELECTOR));
  }

  /**
   * 返回远程数据地址；没有配置时表示表格只做本地交互。
   */
  private remoteSource(): string | null {
    return this.root.getAttribute("data-om-table-src");
  }

  private dataFormat(): "html" | "json" {
    return this.root.getAttribute("data-om-table-format") === "json" ? "json" : "html";
  }

  private isJsonMode(): boolean {
    return this.dataFormat() === "json";
  }

  /**
   * 判断当前表格是否由服务端负责搜索、排序和分页。
   */
  private isServerMode(): boolean {
    return Boolean(this.remoteSource());
  }

  /**
   * 将同源 URL 压缩为相对地址，避免测试和模板输出受域名影响。
   */
  /**
   * 将未知错误转换为可显示的错误消息。
   */
  private errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : this.i18n.t("Request failed");
  }

  /**
   * 返回当前表格管理的本地行集合。
   */
  private localRows(): HTMLElement[] {
    return Array.from(this.root.querySelectorAll<HTMLElement>(TABLE_ROW_SELECTOR));
  }

  /**
   * 读取本地分页大小；未配置时不隐藏分页外的行。
   */
  private pageSize(): number | null {
    const control = this.root.querySelector<HTMLSelectElement | HTMLInputElement>(TABLE_PAGE_SIZE_CONTROL_SELECTOR);
    const rawValue = control?.value || this.root.getAttribute("data-om-table-page-size");
    if (!rawValue) return null;

    const parsed = Number(rawValue);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  /**
   * 对当前过滤后的行进行本地排序，并把排序结果写回 tbody。
   */
  private sortRows(rows: HTMLElement[]): void {
    if (!this.sortState) return;

    const column = this.localColumnMetadata().get(this.sortState.key);
    if (column) {
      if (!column.sortable) return;
      rows.sort((left, right) => this.compareCellValues(left, right, column));
      this.appendSortedRows(rows);
      return;
    }

    const columnIndex = Number(this.sortState.key);
    if (!Number.isFinite(columnIndex)) return;

    rows.sort((left, right) => {
      const leftValue = this.rowCellText(left, columnIndex);
      const rightValue = this.rowCellText(right, columnIndex);
      return this.sortState?.direction === "descending"
        ? rightValue.localeCompare(leftValue, undefined, { numeric: true, sensitivity: "base" })
        : leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });
    });

    this.appendSortedRows(rows);
  }

  /**
   * 把排序后的行重新插入 tbody。
   */
  private appendSortedRows(rows: HTMLElement[]): void {
    const body = rows[0]?.parentElement;
    if (!body) return;

    for (const row of rows) {
      body.append(row);
    }
  }

  /**
   * 返回指定行列的文本内容，用于本地排序。
   */
  private rowCellText(row: HTMLElement, columnIndex: number): string {
    return (row.children.item(columnIndex)?.textContent || "").trim();
  }

  /**
   * 判断一行是否匹配当前搜索词；存在列 metadata 时只搜索 searchable 列。
   */
  private rowMatchesQuery(row: HTMLElement, query: string): boolean {
    if (!query) return true;

    const columns = Array.from(this.localColumnMetadata().values());
    const searchableColumns = columns.filter((column) => column.searchable);
    if (columns.length > 0 && searchableColumns.length === 0) {
      return false;
    }
    if (searchableColumns.length === 0) {
      return row.textContent?.toLocaleLowerCase().includes(query) ?? false;
    }

    return searchableColumns.some((column) => this.cellComparableText(row, column.name).toLocaleLowerCase().includes(query));
  }

  /**
   * 读取表头输出的列 metadata，用于本地排序、搜索和后续导出能力判断。
   */
  private localColumnMetadata(): Map<string, TableColumnMetadata> {
    const columns = new Map<string, TableColumnMetadata>();
    for (const header of this.root.querySelectorAll<HTMLElement>("th[data-om-column]")) {
      const name = header.getAttribute("data-om-column");
      if (!name) continue;
      columns.set(name, {
        name,
        searchable: header.getAttribute("data-om-column-searchable") === "true",
        sortable: header.getAttribute("data-om-column-sortable") === "true",
        type: header.getAttribute("data-om-column-type") || "string"
      });
    }
    return columns;
  }

  /**
   * 按列类型比较两行同名单元格的 raw value。
   */
  private compareCellValues(left: HTMLElement, right: HTMLElement, column: TableColumnMetadata): number {
    const leftValue = this.cellComparableValue(left, column);
    const rightValue = this.cellComparableValue(right, column);
    const result =
      typeof leftValue === "number" && typeof rightValue === "number"
        ? leftValue - rightValue
        : String(leftValue).localeCompare(String(rightValue), undefined, { numeric: true, sensitivity: "base" });
    return this.sortState?.direction === "descending" ? -result : result;
  }

  /**
   * 返回按列类型标准化后的可排序值。
   */
  private cellComparableValue(row: HTMLElement, column: TableColumnMetadata): string | number {
    const value = this.cellComparableText(row, column.name);
    if (column.type === "number" || column.type === "integer" || column.type === "float") {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : 0;
    }
    if (column.type === "boolean") {
      return value === "true" || value === "1" ? 1 : 0;
    }
    return value;
  }

  /**
   * 返回单元格 raw value；没有 raw value 时回退到单元格文本。
   */
  private cellComparableText(row: HTMLElement, columnName: string): string {
    const cell = row.querySelector<HTMLElement>(`td[data-om-column="${cssEscape(columnName)}"]`);
    if (!cell) return "";
    return (cell.getAttribute("data-raw-value") ?? cell.textContent ?? "").trim();
  }

  /**
   * 根据页数重建本地分页按钮；没有分页容器时保持现有页面不变。
   */
  private renderPagination(pageCount: number, windowed = false): void {
    const container = this.root.querySelector<HTMLElement>(TABLE_PAGINATION_SELECTOR);
    if (!container) return;

    const existingButtons = Array.from(container.querySelectorAll<HTMLButtonElement>("button"));
    // The server renders the previous/next controls (icon or text); reuse them as-is on every re-render.
    const previousControl = navigationControl(existingButtons.at(0));
    const nextControl = navigationControl(existingButtons.at(-1));
    container.replaceChildren();
    if (!windowed) {
      for (let page = 1; page <= pageCount; page += 1) {
        container.append(this.paginationButton(page, String(page)));
      }
      return;
    }

    container.append(this.paginationButton(this.currentPage - 1, previousControl, this.currentPage <= 1));
    let previousPage: number | null = null;
    for (const page of paginationWindow(this.currentPage, pageCount)) {
      if (previousPage !== null && page - previousPage > 1) {
        const ellipsis = document.createElement("span");
        ellipsis.className = "om-pagination-ellipsis";
        ellipsis.setAttribute("aria-hidden", "true");
        ellipsis.textContent = "…";
        container.append(ellipsis);
      }
      container.append(this.paginationButton(page, String(page)));
      previousPage = page;
    }
    container.append(this.paginationButton(this.currentPage + 1, nextControl, this.currentPage >= pageCount));
  }

  private paginationButton(page: number, control: string | PaginationControl, disabled = false): HTMLButtonElement {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `om-page-button ${page === this.currentPage ? "is-active" : ""}`.trim();
    if (typeof control === "string") {
      button.textContent = control;
    } else {
      button.classList.add("om-page-button-nav");
      button.innerHTML = control.html;
      if (control.label) button.setAttribute("aria-label", control.label);
    }
    button.disabled = disabled;
    if (!disabled) button.setAttribute("data-om-table-page", String(page));
    if (page === this.currentPage) button.setAttribute("aria-current", "page");
    return button;
  }

  /**
   * 渲染本地分页摘要；没有摘要容器时不输出内容。
   */
  private renderSummary(totalCount: number, visibleCount: number): void {
    const summary = this.root.querySelector<HTMLElement>(TABLE_SUMMARY_SELECTOR);
    if (!summary) return;

    const pageSize = this.pageSize();
    const start = totalCount === 0 ? 0 : pageSize ? (this.currentPage - 1) * pageSize + 1 : 1;
    const end = totalCount === 0 ? 0 : pageSize ? start + visibleCount - 1 : totalCount;
    summary.textContent = `${this.i18n.t("Showing")} ${start} ${this.i18n.t("to")} ${end} ${this.i18n.t("of")} ${totalCount} ${this.i18n.t("entries")}`;
  }

  /**
   * Clear the search box, the initial filters and any external filter form, then reload. A linked
   * TableFilterForm (`data-om-table-target="#<id>"`) resets through its own button so its controls clear too.
   */
  async resetFilters(): Promise<void> {
    const filter = this.root.querySelector<HTMLInputElement>(TABLE_FILTER_SELECTOR);
    if (filter) filter.value = "";
    this.searchInteracted = true;
    this.externalFormParams = null;
    this.externalFormFieldNames = new Set();
    this.currentPage = 1;
    for (const attribute of Array.from(this.root.attributes)) {
      if (!attribute.name.startsWith("data-om-filter-")) continue;
      this.clearedFilterNames.add(attribute.name.replace("data-om-filter-", "").replaceAll("-", "_"));
      this.root.removeAttribute(attribute.name);
    }
    this.root.removeAttribute("data-om-table-initial-query");

    const reset = this.root.id
      ? document.querySelector<HTMLElement>(`[data-om-table-target="#${cssEscape(this.root.id)}"] [data-om-filter-reset]`)
      : null;
    if (reset) {
      reset.click();
      return;
    }
    await this.reload();
  }

  /** Data URL for an export in `format`: current search, filters and sort, never a page (exports cover every matching row). */
  exportUrl(format: string): string {
    const url = new URL(this.buildUrl(), window.location.href);
    url.searchParams.delete("page");
    url.searchParams.delete("page_size");
    url.searchParams.set("export", format);
    return relativeUrl(url);
  }

  /** A same-origin attachment response downloads without leaving the page, so a plain navigation is enough. */
  private download(url: string): void {
    window.location.assign(url);
  }

  /** Ids of the checked rows on the current page, in row order. */
  selectedIds(): string[] {
    return this.visibleRowCheckboxes()
      .filter((checkbox) => checkbox.checked)
      .map((checkbox) => checkbox.value || checkbox.closest(TABLE_ROW_SELECTOR)?.getAttribute("data-om-table-row-id") || "");
  }

  /** Uncheck every row on the current page; bulk actions call this after they finish. */
  clearSelection(): void {
    this.setVisibleRowsSelected(false);
  }

  /**
   * 切换当前可见行的选择框状态。
   */
  private setVisibleRowsSelected(selected: boolean): void {
    for (const row of this.localRows()) {
      if (row.hidden) continue;
      const checkbox = row.querySelector<HTMLInputElement>(TABLE_SELECT_ROW_SELECTOR);
      if (checkbox) checkbox.checked = selected;
    }

    this.syncSelectionState();
  }

  private visibleRowCheckboxes(): HTMLInputElement[] {
    return this.localRows()
      .filter((row) => !row.hidden)
      .map((row) => row.querySelector<HTMLInputElement>(TABLE_SELECT_ROW_SELECTOR))
      .filter((checkbox): checkbox is HTMLInputElement => Boolean(checkbox));
  }

  /**
   * Mirror the row checkboxes into the header checkbox, the toolbar count and the bulk-action slot,
   * and announce the selection whenever the set of ids changes.
   */
  private syncSelectionState(): void {
    const visibleChecks = this.visibleRowCheckboxes();
    const selectedCount = visibleChecks.filter((checkbox) => checkbox.checked).length;

    const selectAll = this.root.querySelector<HTMLInputElement>(TABLE_SELECT_ALL_SELECTOR);
    if (selectAll) {
      selectAll.checked = visibleChecks.length > 0 && selectedCount === visibleChecks.length;
      selectAll.indeterminate = selectedCount > 0 && selectedCount < visibleChecks.length;
    }

    const ids = this.selectedIds();
    const count = this.root.querySelector<HTMLElement>(TABLE_SELECTION_COUNT_SELECTOR);
    if (count) {
      count.textContent = this.i18n.t("{count} selected", { count: ids.length });
      count.hidden = ids.length === 0;
    }
    const bulkActions = this.root.querySelector<HTMLElement>(TABLE_BULK_ACTIONS_SELECTOR);
    if (bulkActions) bulkActions.hidden = ids.length === 0;

    const key = ids.join("\u0000");
    if (key === this.lastSelectionKey) return;
    this.lastSelectionKey = key;
    this.emit<TableSelectionDetail>("om:table:selection", { component: this, ids });
  }

  private preferenceStore(): PreferenceStore {
    if (this.page?.preferences) return this.page.preferences;
    this.fallbackPreferences ??= createPreferenceStore();
    return this.fallbackPreferences;
  }

  /** One preference record per table, keyed by its element id (or data source as a fallback). */
  private viewPreferenceKey(): string {
    return `table:${this.root.id || this.remoteSource() || window.location.pathname}`;
  }

  private restoreViewPreferences(): void {
    const stored = this.preferenceStore().getJson<TableViewPreferences>(this.viewPreferenceKey()) ?? {};
    const remembered = Array.isArray(stored.hiddenColumns) ? stored.hiddenColumns.map(String) : [];
    // Only a column with a toggle can stay hidden: a remembered name the menu no longer offers (pinned,
    // renamed or removed since) would otherwise be hidden with no control to bring it back.
    const hideable = new Set(Array.from(this.root.querySelectorAll<HTMLInputElement>(TABLE_COLUMN_TOGGLE_SELECTOR), (toggle) => toggle.value));
    this.hiddenColumns = new Set(remembered.filter((name) => hideable.has(name)));
    this.density = stored.density === "compact" ? "compact" : "comfortable";
    if (this.hiddenColumns.size !== remembered.length) this.storeViewPreferences();
    this.applyDensity();
    this.syncColumnToggles();
    this.applyColumnVisibility();
  }

  private storeViewPreferences(): void {
    const value: TableViewPreferences = { density: this.density, hiddenColumns: Array.from(this.hiddenColumns) };
    this.preferenceStore().setJson(this.viewPreferenceKey(), value);
  }

  private setColumnHidden(name: string, hidden: boolean): void {
    if (!name) return;
    if (hidden) this.hiddenColumns.add(name);
    else this.hiddenColumns.delete(name);
    this.storeViewPreferences();
    this.syncColumnToggles();
    this.applyColumnVisibility();
  }

  private setDensity(density: TableDensity): void {
    this.density = density;
    this.storeViewPreferences();
    this.applyDensity();
  }

  /** Density lives on the component root so a replaced table body keeps it without re-applying. */
  private applyDensity(): void {
    this.root.setAttribute(TABLE_DENSITY_STATE_ATTRIBUTE, this.density);
    for (const item of this.root.querySelectorAll<HTMLElement>(TABLE_DENSITY_SELECTOR)) {
      const active = item.getAttribute("data-om-table-density") === this.density;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    }
  }

  private syncColumnToggles(): void {
    for (const toggle of this.root.querySelectorAll<HTMLInputElement>(TABLE_COLUMN_TOGGLE_SELECTOR)) {
      toggle.checked = !this.hiddenColumns.has(toggle.value);
    }
  }

  /**
   * Mark the scroll box `is-fit` while the table fits inside it (no sideways scrolling), which lets the
   * sticky header reach the page; re-run after a refresh because the initial partial replaces the box.
   */
  private observeScrollFit(): void {
    const scroll = this.root.querySelector<HTMLElement>(TABLE_SCROLL_SELECTOR);
    if (!scroll) return;
    if (scroll === this.fitObserverTarget) {
      // Same box, new cells (a region refresh): re-measure now instead of waiting for the observer.
      this.fitUpdate?.();
      return;
    }

    this.fitObserver?.disconnect();
    this.fitObserverTarget = scroll;
    const update = () => scroll.classList.toggle(TABLE_SCROLL_FIT_CLASS, scroll.scrollWidth <= scroll.clientWidth);
    this.fitUpdate = update;
    update();
    if (typeof ResizeObserver === "undefined") return;

    this.fitObserver = new ResizeObserver(update);
    this.fitObserver.observe(scroll);
    const table = scroll.querySelector("table");
    if (table) this.fitObserver.observe(table);
  }

  /** Hide the cells of switched-off columns; runs again after every server refresh replaces cells. */
  private applyColumnVisibility(): void {
    if (this.hiddenColumns.size === 0 && !this.root.querySelector(`${TABLE_COLUMN_CELL_SELECTOR.replaceAll("]", "][hidden]")}`)) return;
    for (const cell of this.root.querySelectorAll<HTMLElement>(TABLE_COLUMN_CELL_SELECTOR)) {
      cell.hidden = this.hiddenColumns.has(cell.getAttribute("data-om-column") || "");
    }
  }

  /**
   * 设置当前本地排序状态，并同步表头 aria-sort。
   */
  private setLocalSort(target: HTMLElement): void {
    const key = target.getAttribute("data-om-table-sort") || "";
    const currentDirection =
      this.sortState?.key === key ? this.sortState.direction : target.getAttribute("aria-sort") === "ascending" ? "ascending" : "descending";
    const direction: TableSortDirection = this.sortState?.key === key && currentDirection === "ascending" ? "descending" : "ascending";
    this.sortState = { key, direction };

    this.syncSortControls();
    this.applyLocalView();
  }

  /**
   * 设置服务端排序状态，后续搜索和分页请求会持续携带该状态。
   */
  private setRemoteSort(target: HTMLElement): void {
    const key = target.getAttribute("data-om-table-sort") || "";
    const currentDirection =
      this.sortState?.key === key ? this.sortState.direction : target.getAttribute("aria-sort") === "ascending" ? "ascending" : "descending";
    const direction: TableSortDirection = this.sortState?.key === key && currentDirection === "ascending" ? "descending" : "ascending";
    this.sortState = { key, direction };

    this.syncSortControls();
  }

  /**
   * 将内部排序状态同步到当前 DOM 表头，兼容远程刷新后返回的新节点。
   */
  private syncSortControls(): void {
    for (const sort of this.root.querySelectorAll<HTMLElement>(TABLE_SORT_SELECTOR)) {
      const isActive = Boolean(this.sortState && sort.getAttribute("data-om-table-sort") === this.sortState.key);
      const direction = isActive ? this.sortState!.direction : "none";
      sort.setAttribute("aria-sort", direction);
      sort.classList.toggle("active", isActive);
      const icon = sort.querySelector<HTMLElement>("[data-om-table-sort-icon]");
      if (icon) {
        icon.className = direction === "ascending"
          ? "ri-arrow-up-line"
          : direction === "descending" ? "ri-arrow-down-line" : "ri-arrow-up-down-line";
      }

      const header = sort.closest("th");
      if (!header) continue;

      // DataTables 风格的排序图标依赖 th 状态 class，按钮只负责触发交互和 aria。
      header.classList.toggle("sorting", direction === "none");
      header.classList.toggle("sorting_asc", direction === "ascending");
      header.classList.toggle("sorting_desc", direction === "descending");
    }
  }
}
interface PaginationControl {
  html: string;
  label: string;
}

/** Snapshot a server-rendered previous/next button so client re-renders keep its icon and label. */
function navigationControl(button: HTMLButtonElement | undefined): PaginationControl {
  return {
    html: button?.innerHTML ?? "",
    label: button?.getAttribute("aria-label") ?? ""
  };
}

function paginationWindow(currentPage: number, pageCount: number): number[] {
  if (pageCount <= 9) return Array.from({ length: pageCount }, (_, index) => index + 1);

  const pages = new Set([1, pageCount]);
  for (let page = Math.max(1, currentPage - 2); page <= Math.min(pageCount, currentPage + 2); page += 1) pages.add(page);
  if (currentPage <= 4) for (let page = 1; page <= Math.min(pageCount, 6); page += 1) pages.add(page);
  if (currentPage >= pageCount - 3) for (let page = Math.max(1, pageCount - 5); page <= pageCount; page += 1) pages.add(page);
  return Array.from(pages).sort((left, right) => left - right);
}
