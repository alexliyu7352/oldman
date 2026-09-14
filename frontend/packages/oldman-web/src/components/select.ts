import "./select.scss";
import { Component } from "../core/component/component";
import Choices from "choices.js";

const SELECT_CONTROL_SELECTOR = "[data-om-select-control]";
const SELECT_LOAD_MORE_SELECTOR = "[data-om-select-load-more]";
const SELECT_SEARCH_SELECTOR = "[data-om-select-search]";
const REMOTE_SEARCH_DELAY_MS = 150;

type ChoicesElement = HTMLInputElement | HTMLSelectElement;
type ChoicesOptions = ConstructorParameters<typeof Choices>[1];
interface SelectLoadOptions {
  append?: boolean;
  initialValues?: string[];
  page?: number;
}

interface SelectProviderState {
  hasMore: boolean;
  initialValues: string[];
  page: number;
  query: string;
  source: string;
}

export interface SelectOption {
  data?: Record<string, unknown>;
  disabled?: boolean;
  html?: string;
  label: string;
  selected?: boolean;
  value: string;
}

export interface SelectChangeDetail<TComponent extends Select = Select> {
  component: TComponent;
  values: string[];
}

export interface SelectOptionsDetail<TComponent extends Select = Select> {
  component: TComponent;
  options: SelectOption[];
  url?: string;
}

export interface SelectErrorDetail<TComponent extends Select = Select> {
  component: TComponent;
  error: unknown;
  message: string;
  response?: unknown;
  url?: string;
}

export class SelectProviderResponseError extends Error {
  readonly response: unknown;

  /**
   * 保存原始响应，便于业务侧在错误事件中调试 provider 返回内容。
   */
  constructor(message: string, response: unknown) {
    super(message);
    this.name = "SelectProviderResponseError";
    this.response = response;
  }
}

/**
 * 将字符串数组或标准选项数组归一化为 SelectOption。
 */
export function normalizeSelectOptions(input: unknown): SelectOption[] {
  if (isApiErrorResponse(input)) {
    throw new SelectProviderResponseError(responseMessage(input), input);
  }
  if (isRecord(input) && ("results" in input || "more" in input) && !isProviderResponse(input)) {
    throw new SelectProviderResponseError("Invalid select provider response", input);
  }

  const source = isProviderResponse(input) ? input.results : input;
  if (!Array.isArray(source)) throw new SelectProviderResponseError("Invalid select provider response", input);

  return source
    .map((item) => {
      if (typeof item === "string") return { label: item, value: item };
      if (!isOptionLike(item)) return null;

      return {
        data: isRecord(item.data) ? item.data : undefined,
        disabled: typeof item.disabled === "boolean" ? item.disabled : false,
        html: typeof item.html === "string" ? item.html : undefined,
        label: String(item.label ?? item.text ?? item.value),
        selected: typeof item.selected === "boolean" ? item.selected : false,
        value: String(item.value ?? item.id ?? item.label ?? item.text)
      };
    })
    .filter((item): item is SelectOption => item !== null);
}

/**
 * 基于原生 select 的无头选择组件，提供单选、多选、搜索过滤和远程选项加载。
 */
export class Select extends Component {
  static readonly componentName = "select";
  private choices: Choices | null = null;
  private options: SelectOption[] = [];
  private providerState: SelectProviderState | null = null;
  private requestController: AbortController | null = null;
  private requestSequence = 0;
  private searchTimer: number | null = null;
  private loadingNextPage = false;
  private paginationObserver: IntersectionObserver | null = null;

  /**
   * 绑定选择变化、搜索过滤，并按需加载远程选项。
   */
  override async mount(): Promise<void> {
    this.on("change", SELECT_CONTROL_SELECTOR, () => {
      this.emit<SelectChangeDetail>("om:select:change", { component: this, values: this.selectedValues() });
    });

    this.on("input", SELECT_SEARCH_SELECTOR, () => {
      void this.applySearch();
    });

    const declaredOptions = this.declaredOptions();
    if (declaredOptions.length > 0) this.setOptions(declaredOptions);
    else this.options = this.domOptions();

    const source = this.sourceUrl();
    if (source) await this.loadOptions(source, "", { initialValues: this.initialValues() });
    this.bindDependencies(source);
    this.bindChoicesSearch(source);
    this.mountChoices();
    this.bindChoicesInputSearch(source);
    this.bindImageFallback();
    this.updatePaginationControl();
  }

  /**
   * 销毁 Choices 增强实例并交还原始表单控件。
   */
  override async unmount(): Promise<void> {
    if (this.searchTimer !== null) window.clearTimeout(this.searchTimer);
    this.requestController?.abort();
    this.paginationObserver?.disconnect();
    this.destroyChoices();
  }

  /**
   * 返回当前选择值；多选控件会返回全部选中值。
   */
  selectedValues(): string[] {
    if (this.choices) {
      const value = this.choices.getValue(true);
      if (Array.isArray(value)) return value.map((item) => String(item));
      return value === "" || value === undefined ? [] : [String(value)];
    }

    return Array.from(this.control()?.selectedOptions ?? []).map((option) => option.value);
  }

  /**
   * 从远程 JSON 地址加载选项并渲染到 select。
   */
  async loadOptions(url: string, query = "", options: SelectLoadOptions = {}): Promise<SelectOption[]> {
    const page = options.page ?? 1;
    const initialValues = options.initialValues ?? [];
    const requestUrl = this.providerUrl(url, query, initialValues, page);
    const selectedValues = new Set(this.selectedValues());
    const selectedOptions = this.options.filter((item) => selectedValues.has(item.value));
    const currentOptions = this.options.map((item) => ({
      ...item,
      selected: selectedValues.has(item.value)
    }));
    this.requestController?.abort();
    const controller = new AbortController();
    this.requestController = controller;
    const sequence = ++this.requestSequence;
    try {
      const response = await this.http.getJson<unknown>(requestUrl, { signal: controller.signal });
      if (controller.signal.aborted || sequence !== this.requestSequence) return [];
      const hasMore = isProviderResponse(response) ? response.more : false;
      const normalizedOptions = normalizeSelectOptions(response);
      const loadedOptions = this.applyInitialSelection(normalizedOptions, initialValues);
      const renderedOptions = options.append
        ? deduplicateOptions([...currentOptions, ...loadedOptions])
        : deduplicateOptions([...loadedOptions, ...selectedOptions.map((item) => ({ ...item, selected: true }))]);
      this.clearErrorState();
      this.setOptions(renderedOptions);
      this.providerState = {
        hasMore,
        initialValues,
        page,
        query,
        source: url
      };
      this.updatePaginationControl();
      this.emit<SelectOptionsDetail>("om:select:options", { component: this, options: loadedOptions, url: requestUrl });
      return loadedOptions;
    } catch (error) {
      if (controller.signal.aborted || sequence !== this.requestSequence) return [];
      this.renderErrorState(error);
      this.updatePaginationControl(true);
      this.emit<SelectErrorDetail>("om:select:error", {
        component: this,
        error,
        message: errorMessage(error),
        ...(error instanceof SelectProviderResponseError ? { response: error.response } : {}),
        url: requestUrl
      });
      return [];
    } finally {
      if (this.requestController === controller) this.requestController = null;
    }
  }

  /**
   * 当 provider 返回 more=true 时，继续按相同查询上下文加载下一页。
   */
  async loadNextPage(): Promise<SelectOption[]> {
    const state = this.providerState;
    if (!state?.hasMore || this.loadingNextPage) return [];

    this.loadingNextPage = true;
    try {
      return await this.loadOptions(state.source, state.query, {
        append: true,
        initialValues: state.initialValues,
        page: state.page + 1
      });
    } finally {
      this.loadingNextPage = false;
    }
  }

  /**
   * 启用原生 select 以及可选的 Choices 增强实例。
   */
  enable(): void {
    const control = this.control();
    if (control) control.disabled = false;
    this.choices?.enable();
  }

  /**
   * 禁用原生 select 以及可选的 Choices 增强实例。
   */
  disable(): void {
    const control = this.control();
    if (control) control.disabled = true;
    this.choices?.disable();
  }

  /**
   * 使用标准选项结构替换当前 select 的全部选项。
   */
  setOptions(options: SelectOption[]): void {
    const control = this.control();
    if (!control) return;

    this.options = options;

    control.replaceChildren(
      ...options.map((item) => {
        const option = document.createElement("option");
        option.value = item.value;
        option.textContent = item.label;
        option.disabled = item.disabled ?? false;
        option.selected = item.selected ?? false;
        return option;
      })
    );

    if (this.choices) {
      const choiceList = this.choicesList();
      const scrollTop = choiceList?.scrollTop ?? 0;
      this.choices.setChoices(
        options.map((item, index) => ({
          disabled: item.disabled ?? false,
          label: item.label,
          customProperties: { ...(item.data ?? {}), __omHtml: item.html, __omText: item.label },
          selected: control.options[index]?.selected ?? false,
          value: item.value
        })),
        "value",
        "label",
        true,
        true,
        true
      );
      const renderedList = this.choicesList();
      if (renderedList) renderedList.scrollTop = scrollTop;
      window.requestAnimationFrame(() => {
        const settledList = this.choicesList();
        if (settledList) settledList.scrollTop = scrollTop;
      });
    }
  }

  /**
   * 返回增强下拉中真正滚动的候选列表。
   */
  private choicesList(): HTMLElement | null {
    const container = this.root.closest<HTMLElement>(".choices") ?? this.root.querySelector<HTMLElement>(".choices");
    return container?.querySelector<HTMLElement>(".choices__list--dropdown .choices__list") ?? null;
  }

  /**
   * 读取当前原生 select 中已有选项，用于分页追加远程结果。
   */
  private domOptions(): SelectOption[] {
    const control = this.control();
    if (!control) return [];
    return Array.from(control.options).map((option) => ({
      disabled: option.disabled,
      label: option.textContent ?? option.label,
      selected: option.selected,
      value: option.value
    }));
  }

  /**
   * 清理远程 provider 错误态，避免成功加载后继续显示失败状态。
   */
  private clearErrorState(): void {
    delete this.root.dataset.omStatus;
    const control = this.control();
    if (control) control.removeAttribute("aria-invalid");
  }

  /**
   * 标记当前选择器 provider 读取失败，并保留已有选项不被错误响应覆盖。
   */
  private renderErrorState(_error: unknown): void {
    this.root.dataset.omStatus = "error";
    const control = this.control();
    if (control) control.setAttribute("aria-invalid", "true");
  }

  /**
   * 根据搜索输入隐藏不匹配的 option。
   */
  private async applySearch(): Promise<void> {
    const control = this.control();
    const search = this.root.querySelector<HTMLInputElement>(SELECT_SEARCH_SELECTOR);
    if (!control || !search) return;

    const query = search.value.trim().toLocaleLowerCase();
    const source = this.sourceUrl();
    if (source) {
      this.scheduleLoad(source, query);
      return;
    }

    for (const option of Array.from(control.options)) {
      const matches = option.textContent?.toLocaleLowerCase().includes(query) ?? false;
      option.hidden = query.length > 0 && !matches;
    }
  }

  /**
   * 合并同一组件内的搜索入口，延迟短输入并取消上一条远程请求。
   */
  private scheduleLoad(source: string, query: string): void {
    if (this.searchTimer !== null) window.clearTimeout(this.searchTimer);
    this.searchTimer = window.setTimeout(() => {
      this.searchTimer = null;
      void this.loadOptions(source, query);
    }, REMOTE_SEARCH_DELAY_MS);
  }

  /**
   * 返回远程选项地址，允许地址声明在组件根节点或实际控件节点上。
   */
  private sourceUrl(): string | null {
    return this.root.getAttribute("data-om-select-src") ?? this.control()?.getAttribute("data-om-select-src") ?? null;
  }

  /**
   * 根据后端 provider 协议构造远程请求地址。
   */
  private providerUrl(url: string, query = "", initialValues: string[] = [], page = 1): string {
    const bind = this.attribute("data-om-select-bind");
    const dependentFields = this.attribute("data-om-select-dependent-fields");
    const pageSize = this.attribute("data-om-select-page-size");
    const values = query.trim() ? [] : initialValues.filter((value) => value !== "");
    if (!bind && !dependentFields && !pageSize && !query.trim() && values.length === 0 && page === 1) return url;

    const endpoint = new URL(url, window.location.href);
    if (bind) endpoint.searchParams.set("bind", bind);
    endpoint.searchParams.set("page", String(page));
    if (pageSize) endpoint.searchParams.set("page_size", pageSize);
    this.appendInitialValues(endpoint, values);
    if (query.trim()) endpoint.searchParams.set("q", query.trim());

    for (const [name, value] of this.dependentValues(dependentFields)) {
      endpoint.searchParams.set(`depends[${name}]`, value);
    }
    return this.relativeUrl(endpoint);
  }

  /**
   * 读取当前 select 已有选中值，用于首次远程加载时回显编辑表单初始值。
   */
  private initialValues(): string[] {
    const control = this.control();
    if (!control) return [];
    return Array.from(control.selectedOptions)
      .map((option) => option.value)
      .filter((value) => value !== "");
  }

  /**
   * 按后端 provider 协议追加单选 value 或多选 values 参数。
   */
  private appendInitialValues(endpoint: URL, values: string[]): void {
    if (values.length === 0) return;
    if (values.length === 1 && !this.control()?.multiple) {
      const [value] = values;
      if (value) endpoint.searchParams.set("value", value);
      return;
    }
    for (const value of values) {
      endpoint.searchParams.append("values", value);
    }
  }

  /**
   * Provider 初始值回显通常只返回候选项本身，前端需要按请求值恢复 selected。
   */
  private applyInitialSelection(options: SelectOption[], values: string[]): SelectOption[] {
    if (values.length === 0) return options;
    const selectedValues = new Set(values);
    return options.map((item) => ({ ...item, selected: item.selected || selectedValues.has(item.value) }));
  }

  /**
   * 读取组件根节点或控件节点上的属性。
   */
  private attribute(name: string): string | null {
    return this.root.getAttribute(name) ?? this.control()?.getAttribute(name) ?? null;
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
        const value = this.controlValue(control);
        return value === "" ? [] : [[field, value]];
      });
  }

  /**
   * 读取依赖控件的字符串值。
   */
  private controlValue(control: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement): string {
    if (control instanceof HTMLSelectElement && control.multiple) {
      return Array.from(control.selectedOptions)
        .map((option) => option.value)
        .filter(Boolean)
        .join(",");
    }
    return control.value;
  }

  /**
   * 将同源 URL 压缩为相对地址，避免测试和模板输出受域名影响。
   */
  private relativeUrl(url: URL): string {
    if (url.origin !== window.location.origin) return url.toString();
    return `${url.pathname}${url.search}${url.hash}`;
  }

  /**
   * 读取声明在组件根节点或控件上的本地 JSON 选项。
   */
  private declaredOptions(): SelectOption[] {
    const rawValue = this.root.getAttribute("data-om-select-options") ?? this.control()?.getAttribute("data-om-select-options");
    if (!rawValue) return [];

    try {
      return normalizeSelectOptions(JSON.parse(rawValue));
    } catch {
      return [];
    }
  }

  /**
   * 在显式声明增强时创建 Choices 实例。
   */
  private mountChoices(): void {
    const element = this.choicesControl();
    if (!element || this.choices) return;

    this.choices = new Choices(element, this.choicesOptionsFor(element));
    this.setOptions(this.options);
    if (this.hasChoicesFlag(element, "data-choices-text-disabled-true")) {
      this.choices.disable();
    }
  }

  /**
   * 绑定 Choices 自身的 search 事件，让增强 Select 也能走远程 provider 搜索。
   */
  private bindChoicesSearch(source: string | null): void {
    const control = this.control();
    if (!source || !control) return;

    this.listen(control, "search", (event) => {
      const value = event instanceof CustomEvent && typeof event.detail?.value === "string" ? event.detail.value : "";
      this.scheduleLoad(source, value);
    });
  }

  /**
   * 绑定 Choices 生成的可见搜索框，覆盖部分环境不派发 Choices search 事件的情况。
   */
  private bindChoicesInputSearch(source: string | null): void {
    const input = this.choicesSearchInput();
    if (!source || !input) return;

    this.listen(input, "input", () => {
      this.scheduleLoad(source, input.value);
    });
  }

  /**
   * 依赖字段变化时清空无效选择，并以新依赖重新读取第一页。
   */
  private bindDependencies(source: string | null): void {
    const fields = this.attribute("data-om-select-dependent-fields");
    if (!fields) return;
    const container = this.root.closest("form") ?? this.root;
    for (const name of fields.split(",").map((item) => item.trim()).filter(Boolean)) {
      const control = container.querySelector<HTMLElement>(`[name="${cssEscape(name)}"]`);
      if (!control) continue;
      this.listen(control, "change", () => {
        this.providerState = null;
        this.choices?.removeActiveItems();
        this.setOptions([]);
        this.updatePaginationControl();
        if (source) this.scheduleLoad(source, "");
      });
    }
  }

  /**
   * 候选图片加载失败时隐藏图片，保留同一候选中的文本回退。
   */
  private bindImageFallback(): void {
    const container = this.root.closest<HTMLElement>(".choices") ?? this.root;
    this.listen(container, "error", (event) => {
      if (!(event.target instanceof HTMLImageElement)) return;
      event.target.hidden = true;
      const item = event.target.closest<HTMLElement>(".choices__item--choice");
      if (item && !item.textContent?.trim()) item.textContent = item.getAttribute("aria-label") ?? "";
    }, { capture: true });
  }

  /**
   * 为增强下拉提供自动加载哨兵和可点击的无障碍回退按钮。
   */
  private updatePaginationControl(error = false): void {
    if (!this.choices) return;
    const container = this.root.closest<HTMLElement>(".choices") ?? this.root.querySelector<HTMLElement>(".choices");
    const dropdown = container?.querySelector<HTMLElement>(".choices__list--dropdown");
    if (!dropdown) return;

    let button = dropdown.querySelector<HTMLButtonElement>(SELECT_LOAD_MORE_SELECTOR);
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "om-select-load-more";
      button.setAttribute("data-om-select-load-more", "");
      this.listen(button, "click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        void this.loadNextPage();
      });
      dropdown.append(button);
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
   * 返回 Choices 增强后生成的可见搜索输入框。
   */
  private choicesSearchInput(): HTMLInputElement | null {
    if (!this.choices) return null;
    return (
      this.root.querySelector<HTMLInputElement>(".choices__input--cloned")
      ?? this.root.closest(".choices")?.querySelector<HTMLInputElement>(".choices__input--cloned")
      ?? this.root.parentElement?.querySelector<HTMLInputElement>(".choices__input--cloned")
      ?? null
    );
  }

  /**
   * 销毁 Choices 实例，避免页面切换后遗留包装 DOM 和事件。
   */
  private destroyChoices(): void {
    if (!this.choices) return;

    this.choices.destroy();
    this.choices = null;
  }

  /**
   * 查找需要 Choices 增强的输入框或选择框。
   */
  private choicesControl(): ChoicesElement | null {
    if (this.root instanceof HTMLInputElement || this.root instanceof HTMLSelectElement) {
      if (this.root.hasAttribute("data-choices") || this.root.dataset.omSelectEnhance === "choices") return this.root;
      return null;
    }

    const choicesElement = this.root.querySelector<ChoicesElement>("[data-choices]");
    if (choicesElement) return choicesElement;

    if (this.root.dataset.omSelectEnhance === "choices") return this.control();
    return null;
  }

  /**
   * 将 data-choices 属性映射为 Choices 配置。
   */
  private choicesOptionsFor(element: ChoicesElement): ChoicesOptions {
    const options: ChoicesOptions = {
      loadingText: this.i18n.t("Loading..."),
      noResultsText: this.i18n.t("No results found"),
      noChoicesText: this.i18n.t("No choices available"),
      itemSelectText: this.i18n.t("Press to select"),
      uniqueItemText: this.i18n.t("Only unique values can be added"),
      customAddItemText: this.i18n.t("Only values matching specific conditions can be added"),
      addItemText: (value) => this.i18n.t('Press Enter to add "{value}"', { value }),
      maxItemText: (count) => this.i18n.tn("{count} value can be added", "{count} values can be added", count, { count })
    };

    if (this.attribute("data-om-select-label-mode") === "html") {
      const defaultChoice = Choices.defaults.templates.choice;
      options.callbackOnCreateTemplates = () => ({
        choice: (...args: Parameters<typeof defaultChoice>) => {
          const candidate = defaultChoice(...args);
          const properties = args[1].customProperties;
          if (isRecord(properties) && typeof properties.__omHtml === "string") {
            candidate.innerHTML = properties.__omHtml;
            if (typeof properties.__omText === "string") candidate.setAttribute("aria-label", properties.__omText);
          }
          return candidate;
        }
      });
    }

    if (this.hasChoicesFlag(element, "data-choices-groups")) {
      options.placeholderValue = this.i18n.t("This is a placeholder set in the config");
    }
    if (this.hasChoicesFlag(element, "data-choices-search-false")) {
      options.searchEnabled = false;
    }
    if (this.hasChoicesFlag(element, "data-choices-search-true")) {
      options.searchEnabled = true;
    }
    if (this.hasChoicesFlag(element, "data-choices-removeItem") || this.hasChoicesFlag(element, "data-choices-multiple-remove")) {
      options.removeItemButton = true;
    }
    if (this.hasChoicesFlag(element, "data-choices-sorting-false")) {
      options.shouldSort = false;
    }
    if (this.hasChoicesFlag(element, "data-choices-sorting-true")) {
      options.shouldSort = true;
    }
    if (this.hasChoicesFlag(element, "data-choices-limit")) {
      const limit = this.choicesFlagValue(element, "data-choices-limit");
      options.maxItemCount = limit ? Number(limit) : -1;
    }
    if (this.hasChoicesFlag(element, "data-choices-editItem-true")) {
      options.editItems = true;
    }
    if (this.hasChoicesFlag(element, "data-choices-editItem-false")) {
      options.editItems = false;
    }
    if (this.hasChoicesFlag(element, "data-choices-text-unique-true")) {
      options.duplicateItemsAllowed = false;
    }
    if (this.hasChoicesFlag(element, "data-choices-text-disabled-true")) {
      options.addItems = false;
    }

    return options;
  }

  /**
   * 判断 Choices 配置是否声明在实际控件或组件根节点上。
   */
  private hasChoicesFlag(element: ChoicesElement, name: string): boolean {
    return element.hasAttribute(name) || this.root.hasAttribute(name);
  }

  /**
   * 读取 Choices 配置值，实际控件上的值优先于组件根节点。
   */
  private choicesFlagValue(element: ChoicesElement, name: string): string | null {
    return element.getAttribute(name) ?? this.root.getAttribute(name);
  }

  /**
   * 返回组件管理的原生 select 控件。
   */
  private control(): HTMLSelectElement | null {
    if (this.root instanceof HTMLSelectElement) return this.root;
    return this.root.querySelector<HTMLSelectElement>(SELECT_CONTROL_SELECTOR);
  }
}

/**
 * 判断未知对象是否包含可转换为选项的数据。
 */
function isOptionLike(item: unknown): item is { data?: unknown; disabled?: unknown; html?: unknown; id?: unknown; label?: unknown; selected?: unknown; text?: unknown; value?: unknown } {
  if (typeof item !== "object" || item === null) return false;
  return "value" in item || "label" in item || "id" in item || "text" in item;
}

/**
 * 判断响应是否符合后端 Select provider 协议。
 */
function isProviderResponse(input: unknown): input is { more: boolean; results: unknown[] } {
  return isRecord(input) && Array.isArray(input.results) && typeof input.more === "boolean";
}

/**
 * 判断未知响应是否为 DefaultApiFormResponse 风格的业务错误。
 */
function isApiErrorResponse(input: unknown): input is { error_code: number; errors?: unknown; message?: unknown } {
  return isRecord(input) && typeof input.error_code === "number" && input.error_code !== 0;
}

/**
 * 判断未知值是否为普通对象。
 */
function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null;
}

/**
 * 从 provider 错误响应中提取可展示消息。
 */
function responseMessage(input: { message?: unknown }): string {
  return typeof input.message === "string" && input.message.trim().length > 0
    ? input.message
    : "Select provider request failed";
}

/**
 * 统一把异常转成事件消息，供页面或业务组件显示。
 */
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Select provider request failed";
}

/**
 * 按 value 合并分页结果，并保留已经选中的状态。
 */
function deduplicateOptions(options: SelectOption[]): SelectOption[] {
  const unique = new Map<string, SelectOption>();
  for (const option of options) {
    const current = unique.get(option.value);
    unique.set(option.value, current ? { ...current, selected: Boolean(current.selected || option.selected) } : option);
  }
  return [...unique.values()];
}

/**
 * 转义属性选择器中的字段名，兼容没有 CSS.escape 的测试环境。
 */
function cssEscape(value: string): string {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
}
