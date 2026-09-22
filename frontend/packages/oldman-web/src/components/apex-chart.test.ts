import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApexChart } from "./apex-chart";

const chartInstances: Array<{
  destroy: ReturnType<typeof vi.fn>;
  element: HTMLElement;
  options: unknown;
  render: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  updateSeries: ReturnType<typeof vi.fn>;
  appendData: ReturnType<typeof vi.fn>;
  updateOptions: ReturnType<typeof vi.fn>;
}> = [];

vi.mock("apexcharts", () => {
  return {
    default: class ApexChartsMock {
      readonly render = vi.fn().mockResolvedValue(undefined);
      readonly destroy = vi.fn();
      readonly resize = vi.fn();
      readonly updateSeries = vi.fn().mockResolvedValue(undefined);
      readonly appendData = vi.fn().mockResolvedValue(undefined);
      readonly updateOptions = vi.fn().mockResolvedValue(undefined);

      constructor(element: HTMLElement, options: unknown) {
        chartInstances.push({
          element,
          options,
          render: this.render,
          destroy: this.destroy,
          resize: this.resize,
          updateSeries: this.updateSeries,
          appendData: this.appendData,
          updateOptions: this.updateOptions
        });
      }
    }
  };
});

describe("ApexChart", () => {
  beforeEach(() => {
    chartInstances.length = 0;
    document.body.innerHTML = "";
  });

  it("使用内联 JSON 配置创建、resize 并销毁图表", async () => {
    document.body.innerHTML = `
      <section data-om-chart-config='{"series":[{"data":[1,2]}]}'></section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new ApexChart(root);

    await component.start();
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("success"));
    component.resize();
    await component.stop();

    expect(chartInstances).toHaveLength(1);
    expect(chartInstances[0]!.element).toBe(root);
    expect(chartInstances[0]!.render).toHaveBeenCalledTimes(1);
    expect(chartInstances[0]!.resize).toHaveBeenCalledTimes(1);
    expect(chartInstances[0]!.destroy).toHaveBeenCalledTimes(1);
    expect(root.dataset.omStatus).toBe("success");
  });

  it("从远程 JSON 加载配置", async () => {
    document.body.innerHTML = `
      <section data-om-chart-src="/api/chart">
        <div data-om-chart-target></div>
        <p data-om-chart-loading hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const target = root.querySelector<HTMLElement>("[data-om-chart-target]")!;
    const component = new ApexChart(root);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue({ series: [{ data: [3] }] }) });

    await component.start();
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("success"));

    expect(component.http.getJson).toHaveBeenCalledWith("/api/chart", { signal: expect.any(AbortSignal) });
    expect(chartInstances[0]!.element).toBe(target);
    expect(root.dataset.omStatus).toBe("success");
    expect(root.querySelector<HTMLElement>("[data-om-chart-loading]")!.hidden).toBe(true);

    await component.stop();
  });

  it("安全渲染 summary/meta，并只把 Apex options 交给图表", async () => {
    document.body.innerHTML = `
      <section>
        <div data-om-chart-target></div>
        <div data-om-chart-summary hidden></div>
        <dl data-om-chart-meta hidden></dl>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new ApexChart(root);

    await component.renderChart({
      series: [{ data: [3] }],
      xaxis: { categories: ["Today"] },
      summary: [{ label: "<b>Total</b>", value: 3, tone: "success" }],
      meta: { range: "<script>bad</script>" }
    });

    expect(chartInstances[0]!.options).toEqual({
      series: [{ data: [3] }],
      xaxis: { axisBorder: { show: false }, axisTicks: { show: false }, categories: ["Today"] },
      chart: { fontFamily: "inherit", foreColor: "var(--om-chart-axis-text, #373d3f)", toolbar: { show: false } },
      grid: { strokeDashArray: 4, xaxis: { lines: { show: false } }, borderColor: "var(--om-chart-grid, #e0e0e0)" },
      colors: ["#3b82f6", "#10b981", "#0ea5e9", "#f59e0b", "#f43f5e", "#8b5cf6"],
      dataLabels: { enabled: false }
    });
    expect(root.querySelector("[data-om-chart-summary]")?.textContent).toContain("<b>Total</b>");
    expect(root.querySelector("[data-om-chart-summary] b")).toBeNull();
    expect(root.querySelector("[data-om-chart-meta]")?.textContent).toContain("<script>bad</script>");
    expect(root.querySelector("[data-om-chart-meta] script")).toBeNull();

    await component.stop();
  });

  it("只渲染最后一次远程请求并在卸载时取消请求", async () => {
    document.body.innerHTML = `<section><div data-om-chart-target></div></section>`;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new ApexChart(root);
    const requests: Array<{
      resolve: (value: { series: Array<{ data: number[] }> }) => void;
      signal: AbortSignal | undefined;
    }> = [];
    Object.assign(component.http, {
      getJson: vi.fn((_url: string, config?: { signal?: AbortSignal }) =>
        new Promise<{ series: Array<{ data: number[] }> }>((resolve) => requests.push({ resolve, signal: config?.signal }))
      )
    });

    const first = component.load("/api/chart?range=first");
    const second = component.load("/api/chart?range=second");
    expect(requests[0]!.signal?.aborted).toBe(true);
    requests[1]!.resolve({ series: [{ data: [2] }] });
    await second;
    requests[0]!.resolve({ series: [{ data: [1] }] });
    await first;

    expect(chartInstances).toHaveLength(1);
    expect(chartInstances[0]!.options).toEqual({
      series: [{ data: [2] }],
      xaxis: { axisBorder: { show: false }, axisTicks: { show: false } },
      chart: { fontFamily: "inherit", foreColor: "var(--om-chart-axis-text, #373d3f)", toolbar: { show: false } },
      grid: { strokeDashArray: 4, xaxis: { lines: { show: false } }, borderColor: "var(--om-chart-grid, #e0e0e0)" },
      colors: ["#3b82f6", "#10b981", "#0ea5e9", "#f59e0b", "#f43f5e", "#8b5cf6"],
      dataLabels: { enabled: false }
    });

    const pending = component.load("/api/chart?range=pending");
    await component.stop();
    expect(requests[2]!.signal?.aborted).toBe(true);
    requests[2]!.resolve({ series: [{ data: [3] }] });
    await pending;
    expect(chartInstances).toHaveLength(1);
  });

  it("把实时更新方法直接交给当前 Apex 实例", async () => {
    document.body.innerHTML = `<section><div data-om-chart-target></div></section>`;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new ApexChart(root);

    await expect(component.updateSeries([])).rejects.toThrow("Chart is not rendered");
    await component.renderChart({ series: [{ data: [1] }] });
    await component.updateSeries([{ data: [2] }]);
    await component.appendData([{ data: [3] }]);
    await component.updateOptions({ xaxis: { max: 3 } });

    expect(chartInstances[0]!.updateSeries).toHaveBeenCalledWith([{ data: [2] }]);
    expect(chartInstances[0]!.appendData).toHaveBeenCalledWith([{ data: [3] }]);
    expect(chartInstances[0]!.updateOptions).toHaveBeenCalledWith({ xaxis: { max: 3 } });

    await component.stop();
  });

  it("preserves explicit colors and does not mutate application options", async () => {
    const root = document.createElement("section");
    document.body.append(root);
    const component = new ApexChart(root);
    const options = Object.freeze({
      chart: Object.freeze({ type: "line", foreColor: "#b45309", toolbar: { show: true } }),
      grid: Object.freeze({ borderColor: "#64748b", show: false, strokeDashArray: 0 }),
      xaxis: Object.freeze({ axisBorder: { show: true } }),
      colors: ["#ff0000"],
      series: [{ data: [1] }]
    });
    await component.renderChart(options);
    expect(chartInstances[0]!.options).toEqual({
      ...options,
      chart: { fontFamily: "inherit", ...options.chart },
      grid: { xaxis: { lines: { show: false } }, ...options.grid },
      xaxis: { axisTicks: { show: false }, ...options.xaxis },
      dataLabels: { enabled: false }
    });
    expect((chartInstances[0]!.options as { chart: unknown }).chart).not.toBe(options.chart);
    await component.stop();
  });

  it("gives area charts the signature fill and reads the palette from the stylesheet tokens", async () => {
    const root = document.createElement("section");
    root.style.setProperty("--om-chart-1", "#123456");
    document.body.append(root);
    const component = new ApexChart(root);
    await component.renderChart({ chart: { type: "area" }, series: [{ data: [1] }] });
    const rendered = chartInstances[0]!.options as { colors: string[]; fill: { type: string } };
    expect(rendered.colors[0]).toBe("#123456");
    expect(rendered.colors[1]).toBe("#10b981");
    expect(rendered.fill.type).toBe("gradient");
    await component.stop();
  });

  it("lets an explicit dataLabels option override the disabled default", async () => {
    const root = document.createElement("section");
    document.body.append(root);
    const component = new ApexChart(root);
    await component.renderChart({ series: [{ data: [1] }], dataLabels: { enabled: true, offsetY: -4 } });
    expect((chartInstances[0]!.options as { dataLabels: unknown }).dataLabels).toEqual({ enabled: true, offsetY: -4 });
    await component.stop();
  });

  it("emits a generic render-complete event after successful chart rendering", async () => {
    document.body.innerHTML = `
      <section data-om-chart-config='{"series":[{"data":[1]}]}'></section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const complete = vi.fn();
    root.addEventListener("om:component:render-complete", complete);
    const component = new ApexChart(root);

    await component.renderChart({ series: [{ data: [1] }] });

    expect(complete).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: expect.objectContaining({ component, root })
      })
    );

    await component.stop();
  });

  it("emits a generic render-error event when remote loading fails", async () => {
    document.body.innerHTML = `
      <section data-om-chart-src="/api/chart">
        <p data-om-chart-error hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const error = new Error("图表失败");
    const renderError = vi.fn();
    root.addEventListener("om:component:render-error", renderError);
    const component = new ApexChart(root);
    Object.assign(component.http, { getJson: vi.fn().mockRejectedValue(error) });

    await expect(component.load("/api/chart")).rejects.toThrow("图表失败");

    expect(renderError).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: expect.objectContaining({ component, error, root })
      })
    );

    await component.stop();
  });

  it("远程图表加载期间显示作用域遮罩并隐藏旧文字 loading", async () => {
    document.body.innerHTML = `
      <section data-om-chart-src="/api/chart">
        <div data-om-chart-target></div>
        <div data-om-chart-loading hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new ApexChart(root);
    let resolveChart!: (value: { series: Array<{ data: number[] }> }) => void;
    const chartPromise = new Promise<{ series: Array<{ data: number[] }> }>((resolve) => {
      resolveChart = resolve;
    });
    Object.assign(component.http, { getJson: vi.fn().mockReturnValue(chartPromise) });

    const start = component.start();
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("loading"));
    await start;

    expect(root.dataset.omComponentState).toBe("mounted");

    const preloader = root.querySelector<HTMLElement>("[data-om-scoped-preloader]");
    expect(root.dataset.omPreloaderStatus).toBe("loading");
    expect(preloader).not.toBeNull();
    expect(preloader?.hidden).toBe(false);
    expect(preloader?.textContent).toContain("Loading...");
    expect(root.querySelector<HTMLElement>("[data-om-chart-loading]")!.hidden).toBe(true);

    resolveChart({ series: [{ data: [3] }] });
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("success"));

    expect(root.dataset.omStatus).toBe("success");
    expect(root.dataset.omPreloaderStatus).toBe("idle");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();

    await component.stop();
  });

  it("初始 card loading 覆盖图表时不叠加组件内部遮罩", async () => {
    document.body.innerHTML = `
      <div data-om-loading-initial="true" data-om-preloader-status="loading">
        <div data-om-scoped-preloader>Loading...</div>
        <section data-om-chart-src="/api/chart">
          <div data-om-chart-target></div>
        </section>
      </div>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new ApexChart(root);
    let resolveChart!: (value: { series: Array<{ data: number[] }> }) => void;
    const chartPromise = new Promise<{ series: Array<{ data: number[] }> }>((resolve) => {
      resolveChart = resolve;
    });
    Object.assign(component.http, { getJson: vi.fn().mockReturnValue(chartPromise) });

    const start = component.start();
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("loading"));
    await start;

    expect(root.dataset.omComponentState).toBe("mounted");

    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();
    expect(document.querySelectorAll("[data-om-scoped-preloader]")).toHaveLength(1);

    resolveChart({ series: [{ data: [3] }] });
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("success"));

    await component.stop();
  });

  it("空数据时显示 empty 状态且不创建图表", async () => {
    document.body.innerHTML = `
      <section data-om-chart-config='{"series":[]}'>
        <p data-om-chart-empty hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new ApexChart(root);

    await component.start();
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("empty"));

    expect(chartInstances).toHaveLength(0);
    expect(root.dataset.omStatus).toBe("empty");
    expect(root.querySelector<HTMLElement>("[data-om-chart-empty]")!.hidden).toBe(false);

    await component.stop();
  });

  it("远程加载失败时显示 error 状态并抛出错误", async () => {
    document.body.innerHTML = `
      <section>
        <p data-om-chart-error hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new ApexChart(root);
    Object.assign(component.http, { getJson: vi.fn().mockRejectedValue(new Error("图表失败")) });

    await component.start();

    await expect(component.load("/api/chart")).rejects.toThrow("图表失败");
    expect(root.dataset.omStatus).toBe("error");
    expect(root.querySelector<HTMLElement>("[data-om-chart-error]")!.textContent).toBe("图表失败");

    await component.stop();
  });
});
