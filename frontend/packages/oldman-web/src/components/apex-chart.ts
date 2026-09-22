import ApexCharts from "apexcharts";
import { Component } from "../core/component/component";

const CHART_EMPTY_SELECTOR = "[data-om-chart-empty]";
const CHART_ERROR_SELECTOR = "[data-om-chart-error]";
const CHART_LOADING_SELECTOR = "[data-om-chart-loading]";
const CHART_META_SELECTOR = "[data-om-chart-meta]";
const CHART_SUMMARY_SELECTOR = "[data-om-chart-summary]";
const CHART_TARGET_SELECTOR = "[data-om-chart-target]";

export type ApexChartOptions = Record<string, unknown>;
export type ApexChartStatus = "idle" | "loading" | "success" | "error" | "empty";

const CHART_COLOR_TOKENS = ["--om-chart-1", "--om-chart-2", "--om-chart-3", "--om-chart-4", "--om-chart-5", "--om-chart-6"];
/** Light-theme series palette; used when the stylesheet tokens are not resolvable (tests, detached roots). */
const CHART_COLOR_FALLBACKS = ["#3b82f6", "#10b981", "#0ea5e9", "#f59e0b", "#f43f5e", "#8b5cf6"];

export interface ApexChartInstance {
  destroy(): void;
  render(): Promise<void> | void;
  resize?: () => void;
  updateSeries(series: unknown): Promise<void> | void;
  appendData(data: unknown): Promise<void> | void;
  updateOptions(options: ApexChartOptions): Promise<void> | void;
}

export interface ApexChartRenderDetail<TComponent extends ApexChart = ApexChart> {
  component: TComponent;
  options: ApexChartOptions;
}

export interface ApexChartRenderErrorDetail<TComponent extends ApexChart = ApexChart> {
  component: TComponent;
  error: unknown;
  root: HTMLElement;
}

export interface ApexChartRenderCompleteDetail<TComponent extends ApexChart = ApexChart> {
  component: TComponent;
  root: HTMLElement;
}

/**
 * ApexCharts 无头适配器，负责 JSON 配置、生命周期销毁和状态呈现。
 */
export class ApexChart extends Component {
  static readonly componentName = "apex-chart";

  private chart: ApexChartInstance | null = null;
  private requestController: AbortController | null = null;
  private requestSequence = 0;

  /**
   * 根据模板数据源或内联 JSON 配置初始化图表。
   */
  override async mount(): Promise<void> {
    const source = this.root.getAttribute("data-om-chart-src");
    if (source) {
      this.startInitialLoad(source);
      return;
    }

    const inlineConfig = this.root.getAttribute("data-om-chart-config");
    if (inlineConfig) this.startInitialRender(this.parseOptions(inlineConfig));
  }

  /**
   * 销毁 ApexCharts 实例，避免页面切换后泄漏 SVG 和监听器。
   */
  override async unmount(): Promise<void> {
    this.requestController?.abort();
    this.destroyChart();
  }

  /**
   * 从远程 JSON 地址加载 ApexCharts 配置并渲染。
   */
  async load(url: string): Promise<ApexChartOptions | null> {
    this.requestController?.abort();
    const controller = new AbortController();
    this.requestController = controller;
    const sequence = ++this.requestSequence;
    this.setStatus("loading", this.i18n.t("Loading..."));

    try {
      const options = await this.http.getJson<ApexChartOptions>(url, { signal: controller.signal });
      if (controller.signal.aborted || sequence !== this.requestSequence) return null;
      await this.renderOptions(options, () => !controller.signal.aborted && sequence === this.requestSequence);
      if (controller.signal.aborted || sequence !== this.requestSequence) return null;
      return options;
    } catch (error) {
      if (controller.signal.aborted || sequence !== this.requestSequence) return null;
      this.setStatus("error", this.errorMessage(error));
      this.emitRenderError(error);
      throw error;
    } finally {
      if (this.requestController === controller) this.requestController = null;
    }
  }

  /**
   * 使用统一 JSON 配置渲染图表。
   */
  async renderChart(options: ApexChartOptions): Promise<ApexChartInstance | null> {
    return this.renderOptions(options, () => true);
  }

  /**
   * 用新序列替换当前图表数据，不重建 ApexCharts 实例。
   */
  async updateSeries(series: unknown): Promise<void> {
    await this.currentChart().updateSeries(series);
  }

  /**
   * 向当前图表追加实时数据，不重建 ApexCharts 实例。
   */
  async appendData(data: unknown): Promise<void> {
    await this.currentChart().appendData(data);
  }

  /**
   * 更新当前图表配置，不重建 ApexCharts 实例。
   */
  async updateOptions(options: ApexChartOptions): Promise<void> {
    await this.currentChart().updateOptions(options);
  }

  private async renderOptions(options: ApexChartOptions, isCurrent: () => boolean): Promise<ApexChartInstance | null> {
    this.destroyChart();
    const { summary, meta, ...chartOptions } = options;

    if (this.isEmptyOptions(chartOptions)) {
      if (!isCurrent()) return null;
      this.renderSummary(summary);
      this.renderMeta(meta);
      this.setStatus("empty", this.i18n.t("No chart data"));
      this.emitRenderComplete();
      return null;
    }

    this.setStatus("loading", this.i18n.t("Loading..."));
    this.applyThemeDefaults(chartOptions);
    const chart = new ApexCharts(this.chartTarget(), chartOptions) as ApexChartInstance;
    this.chart = chart;
    await chart.render();
    if (!isCurrent()) {
      if (this.chart === chart) this.destroyChart();
      return null;
    }
    this.renderSummary(summary);
    this.renderMeta(meta);
    this.setStatus("success");
    this.emit<ApexChartRenderDetail>("om:chart:render", { component: this, options: chartOptions });
    this.emitRenderComplete();
    return chart;
  }

  /**
   * Console chart theme: no toolbar, inherited font, dashed horizontal grid only, bare axes,
   * token palette, 22% → 0 area fill and no per-point labels. Every default yields to an explicit
   * option, and nested objects are copied so the caller's options are never mutated.
   */
  private applyThemeDefaults(chartOptions: ApexChartOptions): void {
    // SVG/CSS resolve the text and grid tokens on theme changes without reloading the chart.
    const chartStyle = chartOptions.chart as Record<string, unknown> | undefined;
    const gridStyle = chartOptions.grid as Record<string, unknown> | undefined;
    const xaxisStyle = chartOptions.xaxis as Record<string, unknown> | undefined;
    chartOptions.chart = {
      fontFamily: "inherit",
      ...chartStyle,
      foreColor: chartStyle?.foreColor ?? "var(--om-chart-axis-text, #373d3f)",
      toolbar: { show: false, ...(chartStyle?.toolbar as Record<string, unknown> | undefined) }
    };
    chartOptions.grid = {
      strokeDashArray: 4,
      xaxis: { lines: { show: false } },
      ...gridStyle,
      borderColor: gridStyle?.borderColor ?? "var(--om-chart-grid, #e0e0e0)"
    };
    chartOptions.xaxis = {
      axisBorder: { show: false },
      axisTicks: { show: false },
      ...xaxisStyle
    };
    // Series colours must be real colour strings: ApexCharts derives gradients and legend
    // markers from them, so tokens are read from the computed style instead of passed as var().
    if (!Array.isArray(chartOptions.colors)) chartOptions.colors = this.paletteColors();
    if ((chartOptions.chart as Record<string, unknown>).type === "area" && chartOptions.fill === undefined) {
      chartOptions.fill = {
        type: "gradient",
        gradient: { shadeIntensity: 1, opacityFrom: 0.22, opacityTo: 0, stops: [0, 100] }
      };
    }
    // ApexCharts prints every data point by default, which turns dense series
    // into overlapping labels; dashboards opt in per chart instead.
    const dataLabels = chartOptions.dataLabels as Record<string, unknown> | undefined;
    chartOptions.dataLabels = { enabled: false, ...dataLabels };
  }

  private paletteColors(): string[] {
    const style = window.getComputedStyle(this.root);
    return CHART_COLOR_TOKENS.map((token, index) => style.getPropertyValue(token).trim() || CHART_COLOR_FALLBACKS[index]!);
  }

  /**
   * 请求 ApexCharts 重新计算尺寸。
   */
  resize(): void {
    this.chart?.resize?.();
  }

  /**
   * 销毁当前图表实例。
   */
  destroyChart(): void {
    this.chart?.destroy();
    this.chart = null;
  }

  private currentChart(): ApexChartInstance {
    if (!this.chart) throw new Error("Chart is not rendered");
    return this.chart;
  }

  private chartTarget(): HTMLElement {
    return this.root.querySelector<HTMLElement>(CHART_TARGET_SELECTOR) ?? this.root;
  }

  private isEmptyOptions(options: ApexChartOptions): boolean {
    const series = options.series;
    return Array.isArray(series) && series.length === 0;
  }

  private parseOptions(value: string): ApexChartOptions {
    return JSON.parse(value) as ApexChartOptions;
  }

  private renderSummary(value: unknown): void {
    const container = this.root.querySelector<HTMLElement>(CHART_SUMMARY_SELECTOR);
    if (!container) return;
    container.replaceChildren();
    if (!Array.isArray(value)) {
      container.hidden = true;
      return;
    }
    for (const item of value) {
      if (!item || typeof item !== "object") continue;
      const summary = item as { label?: unknown; tone?: unknown; value?: unknown };
      const row = document.createElement("div");
      row.dataset.omChartSummaryItem = "";
      if (typeof summary.tone === "string") row.dataset.omTone = summary.tone;
      const label = document.createElement("span");
      label.dataset.omChartSummaryLabel = "";
      label.textContent = displayValue(summary.label);
      const itemValue = document.createElement("span");
      itemValue.dataset.omChartSummaryValue = "";
      itemValue.textContent = displayValue(summary.value);
      row.append(label, itemValue);
      container.append(row);
    }
    container.hidden = container.childElementCount === 0;
  }

  private renderMeta(value: unknown): void {
    const container = this.root.querySelector<HTMLElement>(CHART_META_SELECTOR);
    if (!container) return;
    container.replaceChildren();
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      container.hidden = true;
      return;
    }
    for (const [key, metaValue] of Object.entries(value)) {
      const term = document.createElement("dt");
      term.textContent = key;
      const description = document.createElement("dd");
      description.textContent = displayValue(metaValue);
      container.append(term, description);
    }
    container.hidden = container.childElementCount === 0;
  }

  private setStatus(status: ApexChartStatus, message = ""): void {
    this.root.dataset.omStatus = status;
    if (status === "loading") {
      if (this.isCoveredByInitialLoadingScope()) {
        this.preloader.hide();
      } else {
        this.preloader.show(message || this.i18n.t("Loading..."));
      }
    } else {
      this.preloader.hide();
    }

    this.syncStatusElement(CHART_LOADING_SELECTOR, false, "");
    this.syncStatusElement(CHART_ERROR_SELECTOR, status === "error", message);
    this.syncStatusElement(CHART_EMPTY_SELECTOR, status === "empty", message);
  }

  private syncStatusElement(selector: string, visible: boolean, message: string): void {
    const element = this.root.querySelector<HTMLElement>(selector);
    if (!element) return;

    element.textContent = visible ? message : "";
    element.hidden = !visible;
  }

  private isCoveredByInitialLoadingScope(): boolean {
    const scope = this.root.closest<HTMLElement>("[data-om-loading-initial='true']");
    return scope?.dataset.omPreloaderStatus === "loading";
  }

  private errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : this.i18n.t("Request failed");
  }

  private startInitialLoad(url: string): void {
    void this.load(url).catch((error: unknown) => {
      this.logger.error("Oldman chart initial load failed", error);
    });
  }

  private startInitialRender(options: ApexChartOptions): void {
    void this.renderChart(options).catch((error: unknown) => {
      this.setStatus("error", this.errorMessage(error));
      this.emitRenderError(error);
      this.logger.error("Oldman chart initial render failed", error);
    });
  }

  private emitRenderComplete(): void {
    this.emit<ApexChartRenderCompleteDetail>("om:component:render-complete", { component: this, root: this.root });
  }

  private emitRenderError(error: unknown): void {
    this.emit<ApexChartRenderErrorDetail>("om:component:render-error", { component: this, error, root: this.root });
  }
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
