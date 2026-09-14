import { afterEach, describe, expect, it, vi } from "vitest";
import { ApexChart } from "./apex-chart";
import { Table } from "./table";

vi.mock("apexcharts", () => {
  return {
    default: class ApexChartsMock {
      readonly render = vi.fn().mockResolvedValue(undefined);
      readonly destroy = vi.fn();

      constructor(readonly element: HTMLElement, readonly options: unknown) {}
    }
  };
});

describe("initial async component mount", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("does not block component mount on a table initial partial refresh", async () => {
    document.body.innerHTML = `
      <section data-om-component="table" data-om-table-src="/streams">
        <div data-om-table-partial data-om-initial-table-partial>
          <table>
            <tbody>
              <tr data-om-table-initial-loading><td>Loading...</td></tr>
            </tbody>
          </table>
        </div>
        <p data-om-table-loading hidden></p>
        <p data-om-table-error hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const table = new Table(root);
    let resolveRefresh: (html: string) => void = () => {};
    Object.assign(table.http, {
      html: vi.fn().mockImplementation(() => new Promise<string>((resolve) => {
        resolveRefresh = resolve;
      }))
    });

    const start = table.start();
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("loading"));
    await start;

    expect(root.dataset.omComponentState).toBe("mounted");
    expect(root.querySelector("[data-om-scoped-preloader]")).not.toBeNull();

    resolveRefresh(`
      <div data-om-table-partial>
        <table>
          <tbody data-om-table-body>
            <tr data-om-table-row><td>Delta Stream</td></tr>
          </tbody>
        </table>
      </div>
    `);
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("success"));

    expect(root.dataset.omComponentState).toBe("mounted");
    expect(root.dataset.omStatus).toBe("success");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();

    await table.stop();
  });

  it("does not block component mount on a chart initial JSON load", async () => {
    document.body.innerHTML = `
      <section data-om-component="apex-chart" data-om-chart-src="/api/chart">
        <div data-om-chart-target></div>
        <p data-om-chart-loading hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='apex-chart']")!;
    const chart = new ApexChart(root);
    let resolveChart: (value: { series: Array<{ data: number[] }> }) => void = () => {};
    Object.assign(chart.http, {
      getJson: vi.fn().mockImplementation(() => new Promise((resolve) => {
        resolveChart = resolve;
      }))
    });

    const start = chart.start();
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("loading"));
    await start;

    expect(root.dataset.omComponentState).toBe("mounted");
    expect(root.querySelector("[data-om-scoped-preloader]")).not.toBeNull();

    resolveChart({ series: [{ data: [3] }] });
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("success"));

    expect(root.dataset.omComponentState).toBe("mounted");
    expect(root.dataset.omStatus).toBe("success");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();

    await chart.stop();
  });
});
