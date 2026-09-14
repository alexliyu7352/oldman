import { Component } from "../core/component/component";
import { SelectProviderResponseError, normalizeSelectOptions, type SelectOption } from "./select";

const AUTOCOMPLETE_EMPTY_SELECTOR = "[data-om-autocomplete-empty]";
const AUTOCOMPLETE_INPUT_SELECTOR = "[data-om-autocomplete-input]";
const AUTOCOMPLETE_ITEM_SELECTOR = "[data-om-autocomplete-item]";
const AUTOCOMPLETE_LIST_SELECTOR = "[data-om-autocomplete-list]";
const AUTOCOMPLETE_LOAD_MORE_SELECTOR = "[data-om-autocomplete-load-more]";
const AUTOCOMPLETE_LOADING_SELECTOR = "[data-om-autocomplete-loading]";
const REMOTE_SEARCH_DELAY_MS = 150;

export interface AutocompleteSelectDetail<TComponent extends Autocomplete = Autocomplete> {
  component: TComponent;
  option: SelectOption;
}

export interface AutocompleteSuggestionsDetail<TComponent extends Autocomplete = Autocomplete> {
  component: TComponent;
  options: SelectOption[];
  query: string;
  url?: string;
}

export interface AutocompleteErrorDetail<TComponent extends Autocomplete = Autocomplete> {
  component: TComponent;
  error: unknown;
  message: string;
  query: string;
  response?: unknown;
  url?: string;
}

interface AutocompleteLoadOptions {
  append?: boolean;
  initialValue?: string;
  page?: number;
}

interface AutocompleteProviderState {
  hasMore: boolean;
  initialValue?: string;
  page: number;
  query: string;
  source: string;
}

/**
 * 提供无头 autocomplete 能力，负责输入搜索、候选渲染、远程数据和选择事件。
 */
export class Autocomplete extends Component {
  static readonly componentName = "autocomplete";

  private options: SelectOption[] = [];
  private activeIndex = -1;
  private providerState: AutocompleteProviderState | null = null;
  private renderedOptions: SelectOption[] = [];
  private requestController: AbortController | null = null;
  private requestSequence = 0;
  private searchTimer: number | null = null;
  private loadingNextPage = false;
  private paginationObserver: IntersectionObserver | null = null;

  /**
   * 绑定输入搜索和候选点击，并在存在数据源时执行远程查询。
   */
  override async mount(): Promise<void> {
    this.loadDeclaredOptions();
    this.ensureList();
    await this.loadInitialValue();
    this.bindDependencies();
    this.bindImageFallback();

    this.on("input", AUTOCOMPLETE_INPUT_SELECTOR, (event) => {
      const input = event.target instanceof HTMLInputElement ? event.target : this.input();
      if (!input) return;
      this.clearSelection();
      if (this.sourceUrl()) this.scheduleSearch(input.value);
      else void this.search(input.value);
    });

    this.on("keydown", AUTOCOMPLETE_INPUT_SELECTOR, (event) => {
      this.handleKeydown(event);
    });

    this.on("click", AUTOCOMPLETE_ITEM_SELECTOR, (event, target) => {
      event.preventDefault();
      if (!(target instanceof HTMLElement)) return;
      const option = this.options.find((item) => item.value === target.dataset.omAutocompleteItem);
      if (option) this.select(option);
    });

    this.on("click", AUTOCOMPLETE_LOAD_MORE_SELECTOR, (event) => {
      event.preventDefault();
      void this.loadNextPage();
    });
  }

  /**
   * 取消组件仍在等待的搜索和分页请求。
   */
  override async unmount(): Promise<void> {
    if (this.searchTimer !== null) window.clearTimeout(this.searchTimer);
    this.requestController?.abort();
    this.paginationObserver?.disconnect();
  }

  /**
   * 执行本地或远程搜索，并重新渲染候选列表。
   */
  async search(query: string): Promise<SelectOption[]> {
    const source = this.sourceUrl();
    let options: SelectOption[];
    try {
      const remoteOptions = source ? await this.loadRemoteOptions(source, query) : null;
      if (source && remoteOptions === null) return [];
      options = source ? remoteOptions ?? [] : this.filterLocalOptions(query);
    } catch (error) {
      this.renderErrorState(error);
      this.updatePaginationControl(true);
      this.emit<AutocompleteErrorDetail>("om:autocomplete:error", {
        component: this,
        error,
        message: errorMessage(error),
        query,
        ...(error instanceof SelectProviderResponseError ? { response: error.response } : {}),
        ...(source ? { url: source } : {})
      });
      return [];
    }

    this.clearErrorState();
    this.renderOptions(options);
    this.emit<AutocompleteSuggestionsDetail>("om:autocomplete:suggestions", { component: this, options, query, ...(source ? { url: source } : {}) });
    return options;
  }

  /**
   * 设置本地候选数据，适合后端模板直接输出 JSON 后初始化。
   */
  setOptions(options: SelectOption[]): void {
    this.options = options;
  }

  /**
   * 当 provider 返回 more=true 时，继续按相同查询上下文加载下一页候选。
   */
  async loadNextPage(): Promise<SelectOption[]> {
    const state = this.providerState;
    if (!state?.hasMore || this.loadingNextPage) return [];

    this.loadingNextPage = true;
    try {
      const nextOptions = await this.loadRemoteOptions(state.source, state.query, {
        append: true,
        ...(state.initialValue ? { initialValue: state.initialValue } : {}),
        page: state.page + 1
      });
      if (nextOptions === null) return [];
      this.renderOptions(this.options);
      return nextOptions;
    } catch (error) {
      this.renderErrorState(error);
      this.updatePaginationControl(true);
      this.emit<AutocompleteErrorDetail>("om:autocomplete:error", {
        component: this,
        error,
        message: errorMessage(error),
        query: state.query,
        ...(error instanceof SelectProviderResponseError ? { response: error.response } : {}),
        url: state.source
      });
      return [];
    } finally {
      this.loadingNextPage = false;
    }
  }

  /**
   * 选择候选项并同步输入框显示值。
   */
  select(option: SelectOption): void {
    if (option.disabled) return;
    const input = this.input();
    if (input) {
      input.value = option.label;
      input.dataset.omAutocompleteValue = option.value;
    }
    const valueControl = this.valueControl();
    if (valueControl) valueControl.value = option.value;

    this.renderOptions([], false);
    this.emit<AutocompleteSelectDetail>("om:autocomplete:select", { component: this, option });
  }

  /**
   * 延迟连续输入，并让所有远程搜索共用同一条取消链路。
   */
  private scheduleSearch(query: string): void {
    if (this.searchTimer !== null) window.clearTimeout(this.searchTimer);
    this.searchTimer = window.setTimeout(() => {
      this.searchTimer = null;
      void this.search(query);
    }, REMOTE_SEARCH_DELAY_MS);
  }

  /**
   * 可见文本被手工编辑后，隐藏 ID 不再代表有效选择。
   */
  private clearSelection(): void {
    const input = this.input();
    if (input) delete input.dataset.omAutocompleteValue;
    const valueControl = this.valueControl();
    if (valueControl) valueControl.value = "";
  }

  /**
   * 从远程 JSON 接口读取候选项，并同步加载态。
   */
  private async loadRemoteOptions(url: string, query: string, options: AutocompleteLoadOptions = {}): Promise<SelectOption[] | null> {
    const endpoint = new URL(url, window.location.href);
    const bind = this.attribute("data-om-select-bind");
    const page = options.page ?? 1;
    if (query.trim()) endpoint.searchParams.set("q", query.trim());
    if (bind) endpoint.searchParams.set("bind", bind);
    if (bind || page > 1) endpoint.searchParams.set("page", String(page));
    if (this.attribute("data-om-select-page-size")) endpoint.searchParams.set("page_size", this.attribute("data-om-select-page-size")!);
    if (!query.trim() && options.initialValue) endpoint.searchParams.set("value", options.initialValue);
    for (const [name, value] of this.dependentValues(this.attribute("data-om-select-dependent-fields"))) {
      endpoint.searchParams.set(`depends[${name}]`, value);
    }
    this.requestController?.abort();
    const controller = new AbortController();
    this.requestController = controller;
    const sequence = ++this.requestSequence;
    this.setLoading(true);
    try {
      const response = await this.http.getJson<unknown>(this.relativeUrl(endpoint), { signal: controller.signal });
      if (controller.signal.aborted || sequence !== this.requestSequence) return null;
      const loadedOptions = normalizeSelectOptions(response);
      this.providerState = {
        hasMore: isProviderResponse(response) ? response.more : false,
        ...(options.initialValue ? { initialValue: options.initialValue } : {}),
        page,
        query,
        source: url
      };
      this.options = options.append ? deduplicateOptions([...this.options, ...loadedOptions]) : loadedOptions;
      this.updatePaginationControl();
      return loadedOptions;
    } catch (error) {
      if (controller.signal.aborted || sequence !== this.requestSequence) return null;
      throw error;
    } finally {
      if (this.requestController === controller) {
        this.requestController = null;
        this.setLoading(false);
      }
    }
  }

  /**
   * 编辑表单已有隐藏值时，从 provider 回显可见 label。
   */
  private async loadInitialValue(): Promise<void> {
    const source = this.sourceUrl();
    const input = this.input();
    const value = this.valueControl()?.value ?? "";
    if (!source || !input || input.value.trim() || !value) return;

    try {
      const options = await this.loadRemoteOptions(source, "", { initialValue: value });
      if (options === null) return;
      const selected = options[0];
      if (!selected) return;
      input.value = selected.label;
      input.dataset.omAutocompleteValue = selected.value;
    } catch (error) {
      this.renderErrorState(error);
      this.emit<AutocompleteErrorDetail>("om:autocomplete:error", {
        component: this,
        error,
        message: errorMessage(error),
        query: "",
        ...(error instanceof SelectProviderResponseError ? { response: error.response } : {}),
        url: source
      });
    }
  }

  /**
   * 清理远程 provider 错误态，避免成功搜索后保留失败标记。
   */
  private clearErrorState(): void {
    delete this.root.dataset.omStatus;
    this.input()?.removeAttribute("aria-invalid");
  }

  /**
   * 标记候选 provider 读取失败，由页面或业务组件决定如何展示详细错误。
   */
  private renderErrorState(_error: unknown): void {
    this.root.dataset.omStatus = "error";
    this.input()?.setAttribute("aria-invalid", "true");
  }

  /**
   * 根据输入文本过滤本地候选项。
   */
  private filterLocalOptions(query: string): SelectOption[] {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return this.options;
    return this.options.filter((item) => item.label.toLocaleLowerCase().includes(normalized));
  }

  /**
   * 渲染候选列表，并同步空状态和当前键盘焦点。
   */
  private renderOptions(options: SelectOption[], showEmpty = true): void {
    const list = this.list();
    if (!list) return;

    this.renderedOptions = options;
    this.activeIndex = options.findIndex((item) => !item.disabled);
    list.replaceChildren(
      ...options.map((item, index) => {
        const option = document.createElement("button");
        option.type = "button";
        option.dataset.omAutocompleteItem = item.value;
        option.dataset.omAutocompleteIndex = String(index);
        option.className = this.root.getAttribute("data-om-autocomplete-item-class") ?? "om-autocomplete-item";
        if (this.attribute("data-om-select-label-mode") === "html" && item.html) option.innerHTML = item.html;
        else option.textContent = item.label;
        option.setAttribute("aria-label", item.label);
        if (item.disabled) option.disabled = true;
        option.setAttribute("aria-selected", index === this.activeIndex ? "true" : "false");
        return option;
      })
    );
    this.updatePaginationControl();
    list.hidden = options.length === 0 && !(this.providerState?.hasMore ?? false);
    this.renderEmptyState(showEmpty && options.length === 0 && this.inputValue().trim().length > 0);
  }

  /**
   * 依赖字段变化后清除旧 ID、文本、候选和分页，再按新依赖查询。
   */
  private bindDependencies(): void {
    const fields = this.attribute("data-om-select-dependent-fields");
    if (!fields) return;
    const container = this.root.closest("form") ?? this.root;
    for (const name of fields.split(",").map((item) => item.trim()).filter(Boolean)) {
      const control = container.querySelector<HTMLElement>(`[name="${cssEscape(name)}"]`);
      if (!control) continue;
      this.listen(control, "change", () => {
        this.clearSelection();
        const input = this.input();
        if (input) input.value = "";
        this.options = [];
        this.providerState = null;
        this.renderOptions([], false);
        if (this.sourceUrl()) this.scheduleSearch("");
      });
    }
  }

  /**
   * 候选图片失败时隐藏图片，保留候选内的文字内容。
   */
  private bindImageFallback(): void {
    this.listen(this.root, "error", (event) => {
      if (!(event.target instanceof HTMLImageElement)) return;
      event.target.hidden = true;
      const item = event.target.closest<HTMLElement>(AUTOCOMPLETE_ITEM_SELECTOR);
      if (item && !item.textContent?.trim()) item.textContent = item.getAttribute("aria-label") ?? "";
    }, { capture: true });
  }

  /**
   * 同时提供自动加载哨兵和可点击的下一页按钮。
   */
  private updatePaginationControl(error = false): void {
    const list = this.list();
    if (!list) return;
    let button = list.querySelector<HTMLButtonElement>(AUTOCOMPLETE_LOAD_MORE_SELECTOR);
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "om-autocomplete-load-more";
      button.setAttribute("data-om-autocomplete-load-more", "");
      list.append(button);
    }
    button.textContent = error ? this.i18n.t("Retry") : this.i18n.t("Load more");
    button.hidden = !(this.providerState?.hasMore ?? false);

    if (typeof IntersectionObserver === "undefined") return;
    this.paginationObserver ??= new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void this.loadNextPage();
    });
    this.paginationObserver.disconnect();
    if (!button.hidden) this.paginationObserver.observe(button);
  }

  /**
   * 返回 autocomplete 输入框。
   */
  private input(): HTMLInputElement | null {
    if (this.root instanceof HTMLInputElement) return this.root;
    return this.root.querySelector<HTMLInputElement>(AUTOCOMPLETE_INPUT_SELECTOR);
  }

  /**
   * 返回表单实际提交的隐藏值控件。
   */
  private valueControl(): HTMLInputElement | null {
    return this.root.querySelector<HTMLInputElement>("[data-om-autocomplete-value-control]");
  }

  /**
   * 返回远程候选地址，优先支持正式 Select provider 属性。
   */
  private sourceUrl(): string | null {
    return this.root.getAttribute("data-om-autocomplete-src") ?? this.root.getAttribute("data-om-select-src");
  }

  /**
   * 读取组件根节点上的属性。
   */
  private attribute(name: string): string | null {
    return this.root.getAttribute(name);
  }

  /**
   * 读取白名单依赖字段的当前值，空值不提交。
   */
  private dependentValues(fields: string | null): Array<[string, string]> {
    if (!fields) return [];
    const container = this.root.closest("form") ?? this.root;
    return fields
      .split(",")
      .map((field) => field.trim())
      .filter(Boolean)
      .flatMap((field): Array<[string, string]> => {
        const control = container.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(`[name="${cssEscape(field)}"]`);
        if (!control) return [];
        const value = control instanceof HTMLSelectElement && control.multiple
          ? Array.from(control.selectedOptions).map((option) => option.value).filter(Boolean).join(",")
          : control.value;
        return value === "" ? [] : [[field, value]];
      });
  }

  /**
   * 将同源 URL 压缩为相对地址，避免测试和模板输出受域名影响。
   */
  private relativeUrl(url: URL): string {
    if (url.origin !== window.location.origin) return url.toString();
    return `${url.pathname}${url.search}${url.hash}`;
  }

  /**
   * 读取声明在组件根节点或输入框上的本地 JSON 候选项。
   */
  private loadDeclaredOptions(): void {
    const rawValue = this.root.getAttribute("data-om-autocomplete-options") ?? this.input()?.getAttribute("data-om-autocomplete-options");
    if (!rawValue) return;

    try {
      this.setOptions(normalizeSelectOptions(JSON.parse(rawValue)));
    } catch {
      this.setOptions([]);
    }
  }

  /**
   * 处理键盘上下移动、确认选择和关闭候选列表。
   */
  private handleKeydown(event: KeyboardEvent): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      this.moveActive(1);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      this.moveActive(-1);
      return;
    }

    if (event.key === "Enter" && this.activeIndex >= 0) {
      event.preventDefault();
      const option = this.renderedOptions[this.activeIndex];
      if (option) this.select(option);
      return;
    }

    if (event.key === "Escape") {
      this.renderOptions([], false);
    }
  }

  /**
   * 移动当前键盘选中的候选项。
   */
  private moveActive(offset: number): void {
    if (this.renderedOptions.length === 0) return;

    let next = this.activeIndex;
    for (let index = 0; index < this.renderedOptions.length; index += 1) {
      next = (next + offset + this.renderedOptions.length) % this.renderedOptions.length;
      if (!this.renderedOptions[next]?.disabled) break;
    }
    this.activeIndex = this.renderedOptions[next]?.disabled ? -1 : next;
    for (const item of this.root.querySelectorAll<HTMLElement>(AUTOCOMPLETE_ITEM_SELECTOR)) {
      item.setAttribute("aria-selected", item.dataset.omAutocompleteIndex === String(this.activeIndex) ? "true" : "false");
    }
  }

  /**
   * 返回或创建候选列表容器。
   */
  private ensureList(): HTMLElement | null {
    const existing = this.list();
    if (existing) return existing;

    const input = this.input();
    if (!input) return null;

    const list = document.createElement("div");
    list.hidden = true;
    list.setAttribute("data-om-autocomplete-list", "");
    list.className = this.root.getAttribute("data-om-autocomplete-list-class") ?? "om-autocomplete-list";
    input.insertAdjacentElement("afterend", list);
    return list;
  }

  /**
   * 返回候选列表容器。
   */
  private list(): HTMLElement | null {
    if (this.root instanceof HTMLElement && this.root.matches(AUTOCOMPLETE_LIST_SELECTOR)) return this.root;
    return this.root.querySelector<HTMLElement>(AUTOCOMPLETE_LIST_SELECTOR);
  }

  /**
   * 显示或隐藏加载态节点。
   */
  private setLoading(loading: boolean): void {
    const element = this.root.querySelector<HTMLElement>(AUTOCOMPLETE_LOADING_SELECTOR);
    if (!element) return;

    element.hidden = !loading;
    if (loading && !element.textContent?.trim()) element.textContent = this.i18n.t("Loading...");
  }

  /**
   * 显示或隐藏空状态节点。
   */
  private renderEmptyState(empty: boolean): void {
    const element = this.root.querySelector<HTMLElement>(AUTOCOMPLETE_EMPTY_SELECTOR);
    if (!element) return;

    element.hidden = !empty;
    if (empty && !element.textContent?.trim()) element.textContent = this.i18n.t("No results found");
  }

  /**
   * 返回当前输入框文本。
   */
  private inputValue(): string {
    return this.input()?.value ?? "";
  }
}

/**
 * 转义属性选择器中的字段名，兼容没有 CSS.escape 的测试环境。
 */
function cssEscape(value: string): string {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
}

/**
 * 判断响应是否符合后端 provider 分页协议。
 */
function isProviderResponse(input: unknown): input is { more: boolean; results: unknown[] } {
  return typeof input === "object"
    && input !== null
    && Array.isArray((input as { results?: unknown }).results)
    && typeof (input as { more?: unknown }).more === "boolean";
}

/**
 * 统一把异常转成 autocomplete 错误事件消息。
 */
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Autocomplete provider request failed";
}

/**
 * 按 value 合并分页候选，避免滚动加载重复项。
 */
function deduplicateOptions(options: SelectOption[]): SelectOption[] {
  const unique = new Map<string, SelectOption>();
  for (const option of options) {
    if (!unique.has(option.value)) unique.set(option.value, option);
  }
  return [...unique.values()];
}
