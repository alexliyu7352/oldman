import { beforeEach, describe, expect, it, vi } from "vitest";
import { createI18n } from "../core/i18n";
import { Component } from "../core/component/component";
import { ComponentManager } from "../core/component/manager";
import { ComponentRegistry } from "../core/component/registry";
import { Table } from "./table";
import { TableFilterForm } from "./table-filter-form";

describe("Table", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("uses the standard table component name and i18n-backed empty state", async () => {
    document.body.innerHTML = emptyTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root, {
      i18n: createI18n({
        locale: "zh-CN",
        messages: {
          "No matching records": "没有匹配的记录"
        }
      })
    });

    await component.start();
    try {
      expect(Table.componentName).toBe("table");
      expect(root.querySelector<HTMLElement>("[data-om-table-empty]")!.hidden).toBe(false);
      expect(root.querySelector<HTMLElement>("[data-om-table-empty]")!.textContent).toBe("没有匹配的记录");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("filters rows without relying on theme-specific table classes", async () => {
    document.body.innerHTML = tableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;

      filter.value = "beta";
      filter.dispatchEvent(new Event("input", { bubbles: true }));

      expect(root.querySelectorAll<HTMLElement>("[data-om-table-row]:not([hidden])")).toHaveLength(1);
      expect(root.querySelector<HTMLElement>("[data-om-table-row]:not([hidden])")!.textContent).toContain("Beta Stream");
      expect(root.querySelector<HTMLElement>("[data-om-table-empty]")!.hidden).toBe(true);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("updates pagination state through generic data hooks", async () => {
    document.body.innerHTML = tableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      const page1 = root.querySelector<HTMLButtonElement>("[data-om-table-page='1']")!;
      const page2 = root.querySelector<HTMLButtonElement>("[data-om-table-page='2']")!;

      page2.click();

      expect(page2.getAttribute("aria-current")).toBe("page");
      expect(page2.classList.contains("active")).toBe(true);
      expect(page1.hasAttribute("aria-current")).toBe(false);
      expect(page1.classList.contains("active")).toBe(false);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("sorts local server-rendered rows without a remote source", async () => {
    document.body.innerHTML = sortableTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      const sortButton = root.querySelector<HTMLButtonElement>("[data-om-table-sort='1']")!;

      sortButton.click();
      expect(visibleRowTexts(root)).toEqual(["01 Alpha", "02 Beta", "03 Gamma"]);
      expect(sortButton.getAttribute("aria-sort")).toBe("ascending");
      expect(sortButton.closest("th")?.classList.contains("sorting_asc")).toBe(true);

      sortButton.click();
      expect(visibleRowTexts(root)).toEqual(["03 Gamma", "02 Beta", "01 Alpha"]);
      expect(sortButton.getAttribute("aria-sort")).toBe("descending");
      expect(sortButton.closest("th")?.classList.contains("sorting_desc")).toBe(true);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("sorts local rows by column metadata and raw values", async () => {
    document.body.innerHTML = metadataTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      root.querySelector<HTMLButtonElement>("[data-om-table-sort='hits']")!.click();

      expect(visibleRowTexts(root)).toEqual(["02 Beta 2 views delete beta", "01 Alpha 10 views delete alpha"]);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("filters local rows only through searchable column metadata when available", async () => {
    document.body.innerHTML = metadataTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;

      filter.value = "delete beta";
      filter.dispatchEvent(new Event("input", { bubbles: true }));

      expect(root.querySelectorAll<HTMLElement>("[data-om-table-row]:not([hidden])")).toHaveLength(0);

      filter.value = "alpha";
      filter.dispatchEvent(new Event("input", { bubbles: true }));

      expect(visibleRowTexts(root)).toEqual(["01 Alpha 10 views delete alpha"]);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("does not fallback to row text when column metadata marks every column unsearchable", async () => {
    document.body.innerHTML = unsearchableMetadataTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;

      filter.value = "alpha";
      filter.dispatchEvent(new Event("input", { bubbles: true }));

      expect(root.querySelectorAll<HTMLElement>("[data-om-table-row]:not([hidden])")).toHaveLength(0);
      expect(root.querySelector<HTMLElement>("[data-om-table-empty]")!.hidden).toBe(false);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("selects and clears visible rows through the header checkbox", async () => {
    document.body.innerHTML = selectableTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;
      const selectAll = root.querySelector<HTMLInputElement>("[data-om-table-select-all]")!;
      const rowChecks = () => Array.from(root.querySelectorAll<HTMLInputElement>("[data-om-table-select-row]"));

      filter.value = "alpha";
      filter.dispatchEvent(new Event("input", { bubbles: true }));
      selectAll.checked = true;
      selectAll.dispatchEvent(new Event("change", { bubbles: true }));

      expect(rowChecks().map((checkbox) => checkbox.checked)).toEqual([true, false]);
      expect(selectAll.indeterminate).toBe(false);

      selectAll.checked = false;
      selectAll.dispatchEvent(new Event("change", { bubbles: true }));

      expect(rowChecks().every((checkbox) => !checkbox.checked)).toBe(true);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("reports the selection in the toolbar and announces changes", async () => {
    document.body.innerHTML = toolbarTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root, {
      i18n: createI18n({ locale: "zh-CN", messages: { "{count} selected": "已选 {count} 项" } })
    });
    const selections: string[][] = [];
    root.addEventListener("om:table:selection", (event) => {
      selections.push((event as CustomEvent<{ ids: string[] }>).detail.ids);
    });

    await component.start();
    try {
      const count = root.querySelector<HTMLElement>("[data-om-table-selection-count]")!;
      const bulk = root.querySelector<HTMLElement>("[data-om-table-bulk-actions]")!;
      const rowChecks = Array.from(root.querySelectorAll<HTMLInputElement>("[data-om-table-select-row]"));
      expect(count.hidden).toBe(true);
      expect(bulk.hidden).toBe(true);

      // Real clicks: a delegated handler that swallowed clicks would leave the box unchecked.
      rowChecks[1]!.click();

      expect(rowChecks[1]!.checked).toBe(true);
      expect(count.hidden).toBe(false);
      expect(count.textContent).toBe("已选 1 项");
      expect(bulk.hidden).toBe(false);
      expect(component.selectedIds()).toEqual(["2"]);
      expect(selections).toEqual([["2"]]);

      component.clearSelection();

      expect(count.hidden).toBe(true);
      expect(bulk.hidden).toBe(true);
      expect(selections).toEqual([["2"], []]);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("hides toggled-off columns and remembers the choice per table", async () => {
    window.localStorage.clear();
    document.body.innerHTML = toolbarTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      const toggle = root.querySelector<HTMLInputElement>("[data-om-table-column-toggle][value='hits']")!;
      toggle.click();

      expect(toggle.checked).toBe(false);
      expect(root.querySelector<HTMLElement>("th[data-om-column='hits']")!.hidden).toBe(true);
      expect(Array.from(root.querySelectorAll<HTMLElement>("td[data-om-column='hits']"), (cell) => cell.hidden)).toEqual([true, true]);
      expect(root.querySelector<HTMLElement>("th[data-om-column='name']")!.hidden).toBe(false);
      expect(JSON.parse(window.localStorage.getItem("oldman:table:toolbar-table")!)).toEqual({ density: "comfortable", hiddenColumns: ["hits"] });
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }

    document.body.innerHTML = toolbarTableMarkup();
    const rootAgain = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const componentAgain = new Table(rootAgain);
    await componentAgain.start();
    try {
      expect(rootAgain.querySelector<HTMLElement>("th[data-om-column='hits']")!.hidden).toBe(true);
      expect(rootAgain.querySelector<HTMLInputElement>("[data-om-table-column-toggle][value='hits']")!.checked).toBe(false);
    } finally {
      await componentAgain.stop();
      document.body.replaceChildren();
      window.localStorage.clear();
    }
  });

  it("exports the current filters and sort without a page through the toolbar button", async () => {
    document.body.innerHTML = `
      <section data-om-component="table" data-om-table-src="/programmes/table" data-om-table-page-size="2" data-om-filter-channel="BBC" data-om-table-initial-sort="-hits">
        <button type="button" data-om-table-export="csv">Export</button>
        <div data-om-table-partial></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue("<div data-om-table-partial></div>") });
    const originalLocation = window.location;
    const assign = vi.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { ...originalLocation, assign, href: "http://localhost/", origin: "http://localhost" } });

    await component.start();
    try {
      expect(component.exportUrl("csv")).toBe("/programmes/table?filter.channel=BBC&sort=-hits&export=csv");

      root.querySelector<HTMLButtonElement>("[data-om-table-export]")!.click();

      expect(assign).toHaveBeenCalledWith("/programmes/table?filter.channel=BBC&sort=-hits&export=csv");
    } finally {
      await component.stop();
      Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
      document.body.replaceChildren();
    }
  });

  it("renders the shipped empty-state template for an empty JSON page and resets filters from it", async () => {
    document.body.innerHTML = `
      <form id="filters" data-om-table-target="#json-table"><input name="status" value="archived"><button type="button" data-om-filter-reset>Reset</button></form>
      ${remoteJsonTableMarkup().replace('data-om-component="table"', 'id="json-table" data-om-component="table" data-om-filter-status="archived"')}
      <template data-om-table-empty-template="all"><div class="om-empty" data-om-table-empty-state>Nothing yet</div></template>
      <template data-om-table-empty-template="filtered"><div class="om-empty" data-om-table-empty-state data-om-table-empty-filtered>No match <button type="button" data-om-table-empty-reset>Reset filters</button></div></template>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    root.append(...Array.from(document.querySelectorAll("template[data-om-table-empty-template]")));
    const component = new Table(root);
    const getJson = vi.fn().mockResolvedValue(jsonTablePayload({ names: [], filteredTotal: 0, total: 5 }));
    Object.assign(component.http, { getJson });
    const formReset = document.querySelector<HTMLButtonElement>("[data-om-filter-reset]")!;
    const resetClicks = vi.fn();
    formReset.addEventListener("click", resetClicks);

    await component.start();
    try {
      await component.refresh("/streams?filter.status=archived");

      expect(root.querySelector("[data-om-table-empty-filtered]")?.textContent).toContain("No match");
      expect(root.querySelector("tbody td")?.className).toBe("om-table-empty-cell");

      root.querySelector<HTMLButtonElement>("[data-om-table-empty-reset]")!.click();
      await Promise.resolve();

      // The table forgets its own filters and hands the reset to the linked filter form.
      expect(root.hasAttribute("data-om-filter-status")).toBe(false);
      expect(resetClicks).toHaveBeenCalledTimes(1);
      expect(getJson).toHaveBeenCalledTimes(1);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("drops remembered hidden columns that no longer have a toggle", async () => {
    window.localStorage.setItem("oldman:table:toolbar-table", JSON.stringify({ density: "comfortable", hiddenColumns: ["hits", "action"] }));
    document.body.innerHTML = toolbarTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    // The hits column became pinned server-side: its toggle is gone but the old preference still names it.
    root.querySelector("[data-om-table-column-toggle][value='hits']")!.closest("label")!.remove();
    const component = new Table(root);

    await component.start();
    try {
      expect(root.querySelector<HTMLElement>("th[data-om-column='hits']")!.hidden).toBe(false);
      expect(root.querySelector<HTMLElement>("th[data-om-column='name']")!.hidden).toBe(false);
      expect(JSON.parse(window.localStorage.getItem("oldman:table:toolbar-table")!)).toEqual({ density: "comfortable", hiddenColumns: [] });
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("switches density on the component root and marks the active menu item", async () => {
    window.localStorage.clear();
    document.body.innerHTML = toolbarTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      expect(root.getAttribute("data-om-density")).toBe("comfortable");

      root.querySelector<HTMLButtonElement>("[data-om-table-density='compact']")!.click();

      expect(root.getAttribute("data-om-density")).toBe("compact");
      // The density state attribute must not turn the root into a click target of the density handler.
      const selectAll = root.querySelector<HTMLInputElement>("[data-om-table-select-all]")!;
      selectAll.click();
      expect(selectAll.checked).toBe(true);
      expect(Array.from(root.querySelectorAll<HTMLInputElement>("[data-om-table-select-row]"), (box) => box.checked)).toEqual([true, true]);
      expect(root.querySelector<HTMLElement>("[data-om-table-density='compact']")!.getAttribute("aria-pressed")).toBe("true");
      expect(root.querySelector<HTMLElement>("[data-om-table-density='comfortable']")!.classList.contains("active")).toBe(false);
      expect(JSON.parse(window.localStorage.getItem("oldman:table:toolbar-table")!).density).toBe("compact");
    } finally {
      await component.stop();
      document.body.replaceChildren();
      window.localStorage.clear();
    }
  });

  it("marks a fitting scroll box so the sticky header can reach the page, and re-checks after a refresh", async () => {
    document.body.innerHTML = `
      <section data-om-component="table" data-om-table-src="/streams">
        <div data-om-table-partial>
          <div class="om-table-shell"><div class="om-table-scroll"><table><tbody><tr data-om-table-row><td>Alpha</td></tr></tbody></table></div></div>
        </div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const wideBox = (element: HTMLElement, scrollWidth: number, clientWidth: number) => {
      Object.defineProperty(element, "scrollWidth", { configurable: true, value: scrollWidth });
      Object.defineProperty(element, "clientWidth", { configurable: true, value: clientWidth });
    };
    wideBox(root.querySelector<HTMLElement>(".om-table-scroll")!, 900, 600);
    const component = new Table(root);
    Object.assign(component.http, {
      html: vi.fn().mockResolvedValue(`
        <div data-om-table-partial>
          <div class="om-table-shell"><div class="om-table-scroll"><table><tbody><tr data-om-table-row><td>Beta</td></tr></tbody></table></div></div>
        </div>
      `)
    });

    await component.start();
    try {
      const scroll = root.querySelector<HTMLElement>(".om-table-scroll")!;
      expect(scroll.classList.contains("is-fit")).toBe(false);

      // A region refresh keeps the box; narrower content after it must be re-measured without a ResizeObserver.
      wideBox(scroll, 600, 600);
      await component.refresh("/streams?page=2");

      expect(root.querySelector<HTMLElement>(".om-table-scroll")!.classList.contains("is-fit")).toBe(true);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("refreshes a server-rendered HTML partial", async () => {
    document.body.innerHTML = remoteTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    root.querySelector<HTMLInputElement>("[data-om-table-filter]")!.value = "alpha";
    const component = new Table(root);
    Object.assign(component.http, {
      html: vi.fn().mockResolvedValue(`
        <div data-om-table-partial>
          <table>
            <tbody>
              <tr data-om-table-row><td>Delta Stream</td></tr>
            </tbody>
          </table>
        </div>
      `)
    });

    await component.start();
    try {
      await component.refresh("/streams?page=2");

      expect(component.http.html).toHaveBeenCalledWith("/streams?page=2");
      expect(root.querySelector("[data-om-table-partial]")?.textContent).toContain("Delta Stream");
      expect(root.querySelector<HTMLElement>("[data-om-table-row]")!.hidden).toBe(false);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("keeps remote table head while replacing body summary and pagination", async () => {
    document.body.innerHTML = remoteTableWithHeadMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const sortButton = root.querySelector<HTMLButtonElement>("[data-om-table-sort='name']")!;
    sortButton.setAttribute("aria-sort", "ascending");
    const component = new Table(root);
    Object.assign(component.http, {
      html: vi.fn().mockResolvedValue(`
        <div data-om-table-partial>
          <div class="table-responsive table-card">
            <table>
              <thead><tr><th><button type="button" data-om-table-sort="name">Name From Server</button></th></tr></thead>
              <tbody data-om-table-body>
                <tr data-om-table-row><td>Beta Stream</td></tr>
              </tbody>
            </table>
          </div>
          <div data-om-table-summary>Total 2 / 2</div>
          <div data-om-table-pagination><button type="button" data-om-table-page="2">2</button></div>
        </div>
      `)
    });

    await component.start();
    try {
      await component.refresh("/streams?sort=name");

      expect(root.querySelector<HTMLButtonElement>("[data-om-table-sort='name']")).toBe(sortButton);
      expect(sortButton.getAttribute("aria-sort")).toBe("ascending");
      expect(root.querySelector("[data-om-table-partial]")?.textContent).toContain("Beta Stream");
      expect(root.querySelector("[data-om-table-partial]")?.textContent).not.toContain("Name From Server");
      expect(root.querySelector("[data-om-table-summary]")?.textContent).toContain("Total 2 / 2");
      expect(root.querySelector("[data-om-table-page='2']")).toBeTruthy();
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("mounts and unmounts components inserted by remote table refreshes", async () => {
    class ProbeComponent extends Component {
      static readonly componentName = "probe";
      static mountedCount = 0;
      static unmountedCount = 0;

      override async mount(): Promise<void> {
        ProbeComponent.mountedCount += 1;
      }

      override async unmount(): Promise<void> {
        ProbeComponent.unmountedCount += 1;
      }
    }

    document.body.innerHTML = remoteTableWithHeadMarkup();
    const registry = new ComponentRegistry();
    registry.register(Table);
    registry.register(ProbeComponent);
    const manager = new ComponentManager({ registry });

    await manager.mount(document);
    try {
      const table = manager.get<Table>("[data-om-component='table']")!;
      Object.assign(table.http, {
        html: vi
          .fn()
          .mockResolvedValueOnce(`
            <div data-om-table-partial>
              <table>
                <tbody data-om-table-body>
                  <tr data-om-table-row><td><button id="row-probe" data-om-component="probe">Inspect</button></td></tr>
                </tbody>
              </table>
            </div>
          `)
          .mockResolvedValueOnce(`
            <div data-om-table-partial>
              <table>
                <tbody data-om-table-body>
                  <tr data-om-table-row><td>Plain row</td></tr>
                </tbody>
              </table>
            </div>
          `)
      });

      await table.refresh("/streams?page=2");

      expect(ProbeComponent.mountedCount).toBe(1);
      expect(manager.get("#row-probe")).toBeTruthy();

      await table.refresh("/streams?page=3");

      expect(ProbeComponent.unmountedCount).toBe(1);
      expect(manager.get("#row-probe")).toBeNull();
    } finally {
      await manager.unmount(document);
      document.body.replaceChildren();
    }
  });

  it("syncs remote sort state to header classes without replacing the head", async () => {
    document.body.innerHTML = remoteTableWithHeadMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const sortButton = root.querySelector<HTMLButtonElement>("[data-om-table-sort='name']")!;
    const head = root.querySelector("thead");
    const component = new Table(root);
    Object.assign(component.http, {
      html: vi.fn().mockResolvedValue(`
        <div data-om-table-partial>
          <table>
            <tbody data-om-table-body>
              <tr data-om-table-row><td>Beta Stream</td></tr>
            </tbody>
          </table>
        </div>
      `)
    });

    await component.start();
    try {
      sortButton.click();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?sort=name"));
      expect(sortButton.getAttribute("aria-sort")).toBe("ascending");
      expect(sortButton.closest("th")?.classList.contains("sorting_asc")).toBe(true);
      expect(root.querySelector("thead")).toBe(head);

      sortButton.click();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?sort=-name"));
      expect(sortButton.getAttribute("aria-sort")).toBe("descending");
      expect(sortButton.closest("th")?.classList.contains("sorting_desc")).toBe(true);
      expect(root.querySelector("thead")).toBe(head);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("keeps server-rendered refresh scoped when multiple tables share one page", async () => {
    document.body.innerHTML = `
      ${remoteTableMarkup({ rootAttrs: 'id="channels-table"' })}
      ${remoteTableMarkup({ rootAttrs: 'id="programmes-table"' })}
    `;
    const channelsRoot = document.querySelector<HTMLElement>("#channels-table")!;
    const programmesRoot = document.querySelector<HTMLElement>("#programmes-table")!;
    channelsRoot.setAttribute("data-om-table-src", "/channels/table");
    programmesRoot.setAttribute("data-om-table-src", "/programmes/table");
    const channelsTable = new Table(channelsRoot);
    const programmesTable = new Table(programmesRoot);
    Object.assign(channelsTable.http, {
      html: vi.fn().mockResolvedValue(`
        <div data-om-table-partial>
          <table><tbody><tr data-om-table-row><td>Only Channels</td></tr></tbody></table>
        </div>
      `)
    });
    Object.assign(programmesTable.http, {
      html: vi.fn().mockResolvedValue(`
        <div data-om-table-partial>
          <table><tbody><tr data-om-table-row><td>Only Programmes</td></tr></tbody></table>
        </div>
      `)
    });

    await channelsTable.start();
    await programmesTable.start();
    try {
      const filter = channelsRoot.querySelector<HTMLInputElement>("[data-om-table-filter]")!;
      filter.value = "news";
      filter.dispatchEvent(new Event("input", { bubbles: true }));

      await vi.waitFor(() => {
        expect(channelsTable.http.html).toHaveBeenCalledWith("/channels/table?q=news");
        expect(channelsRoot.querySelector("[data-om-table-partial]")?.textContent).toContain("Only Channels");
      });
      expect(programmesTable.http.html).not.toHaveBeenCalled();
      expect(programmesRoot.querySelector("[data-om-table-partial]")?.textContent).not.toContain("Only Channels");
      expect(programmesRoot.querySelector("[data-om-table-partial]")?.textContent).toContain("Alpha Stream");
    } finally {
      await programmesTable.stop();
      await channelsTable.stop();
      document.body.replaceChildren();
    }
  });

  it("refreshes when receiving an om:table:reload event", async () => {
    document.body.innerHTML = remoteTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      root.dispatchEvent(new CustomEvent("om:table:reload", { bubbles: true }));

      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams"));
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("loads the first server-rendered partial when the shell starts empty", async () => {
    document.body.innerHTML = remoteTableEmptyShellMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(serverTablePartialMarkup()) });

    await component.start();
    try {
      await vi.waitFor(() => expect(visibleRowTexts(root)).toEqual(["03 Delta"]));
      expect(component.http.html).toHaveBeenCalledWith("/streams?page_size=1");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("loads the first server-rendered partial when the shell starts with an initial loading fragment", async () => {
    document.body.innerHTML = remoteTableInitialShellMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const partial = root.querySelector<HTMLElement>("[data-om-table-partial]")!;
    const initialLoadingRow = root.querySelector<HTMLTableRowElement>("[data-om-table-initial-loading]")!;
    const component = new Table(root);
    let resolveRefresh: (html: string) => void = () => {};
    Object.assign(component.http, {
      html: vi.fn().mockImplementation(() => new Promise<string>((resolve) => {
        resolveRefresh = resolve;
      }))
    });

    expect(partial.hasAttribute("data-om-initial-table-partial")).toBe(true);
    expect(initialLoadingRow.style.visibility).toBe("");

    const start = component.start();
    try {
      await vi.waitFor(() => expect(root.dataset.omStatus).toBe("loading"));
      expect(initialLoadingRow.style.visibility).toBe("hidden");
      expect(initialLoadingRow.getAttribute("aria-hidden")).toBe("true");

      resolveRefresh(serverTablePartialWithFooterMarkup());
      await start;
      await vi.waitFor(() => expect(visibleRowTexts(root)).toEqual(["03 Delta"]));
      expect(component.http.html).toHaveBeenCalledWith("/streams?page_size=1");
      expect(partial.hasAttribute("data-om-initial-table-partial")).toBe(false);
      expect(root.querySelector("[data-om-table-summary]")?.textContent).toContain("Showing 1 to 1 of 1 entries");
      expect(root.querySelector("[data-om-table-pagination]")?.textContent).toContain("Next");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("reports mounted without waiting for the first server-rendered partial", async () => {
    document.body.innerHTML = remoteTableInitialShellMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    let resolveRefresh: (html: string) => void = () => {};
    Object.assign(component.http, {
      html: vi.fn().mockImplementation(() => new Promise<string>((resolve) => {
        resolveRefresh = resolve;
      }))
    });

    const start = component.start();
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("loading"));
    await start;
    expect(root.dataset.omComponentState).toBe("mounted");
    expect(root.querySelector("[data-om-scoped-preloader]")).not.toBeNull();

    resolveRefresh(serverTablePartialWithFooterMarkup());
    await vi.waitFor(() => expect(root.dataset.omStatus).toBe("success"));

    expect(root.dataset.omComponentState).toBe("mounted");
    expect(root.dataset.omStatus).toBe("success");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();

    await component.stop();
    document.body.replaceChildren();
  });

  it("loads the first server-rendered partial with the initial query input value", async () => {
    document.body.innerHTML = remoteTableEmptyShellMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    root.querySelector<HTMLInputElement>("[data-om-table-filter]")!.value = "bbc";
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(serverTablePartialMarkup()) });

    await component.start();
    try {
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=bbc&page_size=1"));
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("keeps the latest server refresh when responses resolve out of order", async () => {
    document.body.innerHTML = remoteTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    const firstRefresh = deferred<string>();
    const secondRefresh = deferred<string>();
    Object.assign(component.http, {
      html: vi
        .fn()
        .mockReturnValueOnce(firstRefresh.promise)
        .mockReturnValueOnce(secondRefresh.promise)
    });

    await component.start();
    try {
      const firstPromise = component.refresh("/streams?page=1");
      const secondPromise = component.refresh("/streams?page=2");

      secondRefresh.resolve(`
        <div data-om-table-partial>
          <table><tbody><tr data-om-table-row><td>Second Page</td></tr></tbody></table>
        </div>
      `);
      await secondPromise;

      firstRefresh.resolve(`
        <div data-om-table-partial>
          <table><tbody><tr data-om-table-row><td>First Page</td></tr></tbody></table>
        </div>
      `);
      await firstPromise;

      expect(root.querySelector("[data-om-table-partial]")?.textContent).toContain("Second Page");
      expect(root.querySelector("[data-om-table-partial]")?.textContent).not.toContain("First Page");
      expect(root.dataset.omStatus).toBe("success");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("renders remote JSON through the existing Table DOM and refresh event", async () => {
    document.body.innerHTML = remoteJsonTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    const refreshed = vi.fn();
    root.addEventListener("om:table:refresh", refreshed);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue(jsonTablePayload({ filteredTotal: 100 })),
      html: vi.fn()
    });

    await component.start();
    try {
      await component.refresh("/streams?page_size=10");

      expect(component.http.getJson).toHaveBeenCalledWith("/streams?page_size=10");
      expect(component.http.html).not.toHaveBeenCalled();
      expect(Array.from(root.querySelectorAll("[data-om-table-row]"), (row) => row.textContent?.trim())).toEqual(["1Alpha", "2Beta"]);
      expect(root.querySelector("td[data-om-column='name']")?.innerHTML).toContain("<strong>Alpha</strong>");
      expect(root.querySelector("td[data-om-column='id']")?.getAttribute("data-raw-value")).toBe("1");
      expect(root.querySelector("[data-om-table-summary]")?.textContent).toContain("Showing 1 to 2 of 100 entries");
      expect(root.querySelector("[data-om-table-page='10']")).toBeTruthy();
      expect(root.querySelector("[data-om-table-page='7']")).toBeNull();
      expect(root.querySelector("[data-om-initial-table-partial]")).toBeNull();
      expect((refreshed.mock.calls[0]![0] as CustomEvent).detail).toEqual({
        component,
        format: "json",
        url: "/streams?page_size=10"
      });
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("keeps server ownership of JSON search, sort, pagination, and row order", async () => {
    document.body.innerHTML = remoteJsonTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue(jsonTablePayload({ filteredTotal: 20, names: ["Zulu", "Alpha"] })),
      html: vi.fn()
    });

    await component.start();
    try {
      const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;
      filter.value = "alpha";
      filter.dispatchEvent(new Event("input", { bubbles: true }));
      await vi.waitFor(() => expect(component.http.getJson).toHaveBeenCalledWith("/streams?q=alpha&page_size=10"));

      root.querySelector<HTMLButtonElement>("[data-om-table-sort='name']")!.click();
      await vi.waitFor(() => expect(component.http.getJson).toHaveBeenCalledWith("/streams?q=alpha&page_size=10&sort=name"));
      await vi.waitFor(() => expect(root.querySelector("[data-om-table-page='2']")).toBeTruthy());

      root.querySelector<HTMLButtonElement>("[data-om-table-page='2']")!.click();
      await vi.waitFor(() => expect(component.http.getJson).toHaveBeenCalledWith("/streams?q=alpha&page_size=10&page=2&sort=name"));

      expect(Array.from(root.querySelectorAll("td[data-om-column='name']"), (cell) => cell.textContent)).toEqual(["Zulu", "Alpha"]);
      expect(Array.from(root.querySelectorAll("[data-om-table-row]"), (row) => row.getAttribute("data-om-table-row-id"))).toEqual(["1", "2"]);
      expect(component.http.html).not.toHaveBeenCalled();
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("rejects malformed JSON table payloads before replacing the DOM", async () => {
    const invalidPayloads = [
      { ...jsonTablePayload(), columns: [] },
      jsonTablePayload({ omitCell: true }),
      jsonTablePayload({ invalidRawValue: true }),
      jsonTablePayload({ missingRowId: true })
    ];

    for (const payload of invalidPayloads) {
      document.body.innerHTML = remoteJsonTableMarkup();
      const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
      const component = new Table(root);
      Object.assign(component.http, { getJson: vi.fn().mockResolvedValue(payload) });
      await component.start();
      await expect(component.refresh("/streams")).rejects.toThrow();
      expect(root.dataset.omStatus).toBe("error");
      expect(root.querySelector("[data-om-table-row]")?.textContent).toContain("Existing");
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("mounts JSON row components and clears current-page selection on refresh", async () => {
    class JsonProbeComponent extends Component {
      static readonly componentName = "json-probe";
      static mountedCount = 0;
      static unmountedCount = 0;

      override async mount(): Promise<void> {
        JsonProbeComponent.mountedCount += 1;
      }

      override async unmount(): Promise<void> {
        JsonProbeComponent.unmountedCount += 1;
      }
    }

    document.body.innerHTML = remoteJsonTableMarkup();
    const registry = new ComponentRegistry();
    registry.register(Table);
    registry.register(JsonProbeComponent);
    const manager = new ComponentManager({ registry });

    await manager.mount(document);
    try {
      const table = manager.get<Table>("[data-om-component='table']")!;
      Object.assign(table.http, {
        getJson: vi
          .fn()
          .mockResolvedValueOnce(jsonTablePayload({ component: "json-probe" }))
          .mockResolvedValueOnce(jsonTablePayload())
      });

      await table.refresh("/streams?page=1");
      expect(JsonProbeComponent.mountedCount).toBe(1);

      const selectAll = document.querySelector<HTMLInputElement>("[data-om-table-select-all]")!;
      selectAll.checked = true;
      selectAll.dispatchEvent(new Event("change", { bubbles: true }));
      expect(Array.from(document.querySelectorAll<HTMLInputElement>("[data-om-table-select-row]"), (checkbox) => checkbox.checked)).toEqual([true, true]);

      await table.refresh("/streams?page=2");
      expect(JsonProbeComponent.unmountedCount).toBe(1);
      expect(Array.from(document.querySelectorAll<HTMLInputElement>("[data-om-table-select-row]"), (checkbox) => checkbox.checked)).toEqual([false, false]);
      expect(selectAll.checked).toBe(false);
    } finally {
      await manager.unmount(document);
      document.body.replaceChildren();
    }
  });

  it("keeps the latest JSON response when requests resolve out of order", async () => {
    document.body.innerHTML = remoteJsonTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    const firstRefresh = deferred<unknown>();
    const secondRefresh = deferred<unknown>();
    Object.assign(component.http, {
      getJson: vi.fn().mockReturnValueOnce(firstRefresh.promise).mockReturnValueOnce(secondRefresh.promise)
    });

    await component.start();
    try {
      const firstPromise = component.refresh("/streams?q=first");
      const secondPromise = component.refresh("/streams?q=second");
      secondRefresh.resolve(jsonTablePayload({ names: ["Second"] }));
      await secondPromise;
      firstRefresh.resolve(jsonTablePayload({ names: ["First"] }));
      await firstPromise;

      expect(root.querySelector("td[data-om-column='name']")?.textContent).toBe("Second");
      expect(root.textContent).not.toContain("First");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("keeps the latest JSON refresh when an older DOM commit is still unmounting", async () => {
    const unmountStarted = deferred<void>();
    const allowUnmount = deferred<void>();
    let delayUnmount = false;

    class SlowUnmountComponent extends Component {
      static readonly componentName = "slow-unmount";

      override async unmount(): Promise<void> {
        if (!delayUnmount) return;
        unmountStarted.resolve(undefined);
        await allowUnmount.promise;
      }
    }

    document.body.innerHTML = remoteJsonTableMarkup();
    const registry = new ComponentRegistry();
    registry.register(Table);
    registry.register(SlowUnmountComponent);
    const manager = new ComponentManager({ registry });

    await manager.mount(document);
    try {
      const table = manager.get<Table>("[data-om-component='table']")!;
      Object.assign(table.http, {
        getJson: vi
          .fn()
          .mockResolvedValueOnce(jsonTablePayload({ component: "slow-unmount" }))
          .mockResolvedValueOnce(jsonTablePayload({ names: ["First"] }))
          .mockResolvedValueOnce(jsonTablePayload({ names: ["Second"] }))
      });

      await table.refresh("/streams?setup=1");
      delayUnmount = true;

      const firstPromise = table.refresh("/streams?q=first");
      await unmountStarted.promise;
      const secondPromise = table.refresh("/streams?q=second");
      await new Promise<void>((resolve) => setTimeout(resolve, 0));

      allowUnmount.resolve(undefined);
      await Promise.all([firstPromise, secondPromise]);

      expect(document.querySelector("td[data-om-column='name']")?.textContent).toBe("Second");
      expect(document.body.textContent).not.toContain("First");
    } finally {
      allowUnmount.resolve(undefined);
      await manager.unmount(document);
      document.body.replaceChildren();
    }
  });

  it("builds remote URLs from search, sort, and page controls", async () => {
    document.body.innerHTML = remoteTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;
      filter.value = "alpha";
      filter.dispatchEvent(new Event("input", { bubbles: true }));
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=alpha"));

      root.querySelector<HTMLButtonElement>("[data-om-table-sort]")!.click();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=alpha&sort=name"));

      root.querySelector<HTMLButtonElement>("[data-om-table-sort]")!.click();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=alpha&sort=-name"));

      root.querySelector<HTMLButtonElement>("[data-om-table-page='2']")!.click();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=alpha&page=2&sort=-name"));
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("resetting filters also removes their parameters from the browser URL", async () => {
    window.history.replaceState(null, "", "/records?status=archived");
    document.body.innerHTML = remoteTableMarkup({ rootAttrs: 'data-om-table-sync-url="true" data-om-filter-status="archived"' });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      await component.refresh();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenLastCalledWith(expect.stringContaining("filter.status=archived")));
      expect(new URLSearchParams(window.location.search).get("status")).toBe("archived");

      await component.resetFilters();

      // The request dropped the filter, and so must the page URL, or a refresh brings the filter back.
      expect(component.http.html).toHaveBeenLastCalledWith(expect.not.stringContaining("filter.status"));
      await vi.waitFor(() => expect(new URLSearchParams(window.location.search).has("status")).toBe(false));
      expect(window.location.pathname).toBe("/records");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("restores direct table state and keeps it in the browser URL for HistoryBack", async () => {
    const turboState = { turbo: { restorationIndex: 7 } };
    window.history.replaceState(turboState, "", "/records?q=alpha&page_size=10&page=2&sort=-name&status=active");
    document.body.innerHTML = remoteTableMarkup({
      rootAttrs:
        'data-om-table-sync-url="true" data-om-table-default-page-size="20" data-om-table-initial-query="alpha" data-om-table-page-size="10" data-om-table-initial-page="2" data-om-table-initial-sort="-name" data-om-filter-status="active"'
    });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      await component.refresh();
      await vi.waitFor(() =>
        expect(component.http.html).toHaveBeenCalledWith(
          "/streams?filter.status=active&q=alpha&page_size=10&page=2&sort=-name"
        )
      );
      await vi.waitFor(() => expect(window.location.pathname).toBe("/records"));

      expect(Object.fromEntries(new URLSearchParams(window.location.search))).toEqual({
        page: "2",
        page_size: "10",
        q: "alpha",
        sort: "-name",
        status: "active"
      });
      expect(window.history.state).toEqual(turboState);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("allows a synchronized built-in search to clear its persisted query", async () => {
    window.history.replaceState({}, "", "/records");
    document.body.innerHTML = remoteTableMarkup({
      rootAttrs: 'data-om-table-sync-url="true"',
    });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      filter.value = "beta";
      filter.dispatchEvent(new Event("input", { bubbles: true }));
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=beta"));
      await vi.waitFor(() => expect(root.getAttribute("data-om-table-initial-query")).toBe("beta"));

      filter.value = "";
      filter.dispatchEvent(new Event("input", { bubbles: true }));
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams"));
      await vi.waitFor(() => expect(root.hasAttribute("data-om-table-initial-query")).toBe(false));
      await vi.waitFor(() => expect(window.location.pathname + window.location.search).toBe("/records"));
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("records the request state in the page URL before the response lands", async () => {
    // 用户点了第 2 页就立刻去点"新增"时，Turbo 会在响应回来之前缓存快照并换页。
    // 地址栏和根节点状态必须在发请求的那一刻就写好，否则这一页的状态就随快照一起丢了。
    window.history.replaceState({}, "", "/records");
    document.body.innerHTML = remoteTableMarkup({ rootAttrs: 'data-om-table-sync-url="true"' });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    const pending = deferred<string>();
    Object.assign(component.http, { html: vi.fn().mockReturnValue(pending.promise) });

    await component.start();
    const refresh = component.refresh("/streams?page=2&sort=-name");
    try {
      expect(window.location.pathname + window.location.search).toBe("/records?page=2&sort=-name");
      expect(root.getAttribute("data-om-table-initial-page")).toBe("2");
      expect(root.getAttribute("data-om-table-initial-sort")).toBe("-name");
    } finally {
      pending.resolve('<div data-om-table-partial></div>');
      await refresh;
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("leaves a torn-down component alone when its response lands late", async () => {
    // Turbo 渲染时 Page.setState("unmounting") 先 abort 页面信号，组件随后卸载；
    // 赶在这之前落地的响应不能再改写已经不属于自己的 DOM。
    window.history.replaceState({}, "", "/records");
    document.body.innerHTML = remoteTableMarkup({ rootAttrs: 'data-om-table-sync-url="true"' });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    const pending = deferred<string>();
    Object.assign(component.http, { html: vi.fn().mockReturnValue(pending.promise) });

    await component.start();
    const refresh = component.refresh("/streams?page=2");
    await component.stop();
    pending.resolve('<div data-om-table-partial><table><tbody><tr data-om-table-row><td>Late Stream</td></tr></tbody></table></div>');
    await refresh;

    expect(root.textContent).not.toContain("Late Stream");
    expect(root.dataset.omStatus).not.toBe("success");
    document.body.replaceChildren();
  });

  it("does not let a stateless refresh erase the state already in the page URL", async () => {
    // Turbo 还原之后组件可能先于服务端注入的状态挂载完成，这时它会按默认值刷新一次。
    // syncPageUrl 用的是 replaceState，改的就是这条历史条目本身：抹掉了，用户再按取消/后退
    // 回来的就是一个没有筛选的列表。
    const turboState = { turbo: { restorationIndex: 4 } };
    window.history.replaceState(turboState, "", "/records?q=alpha&sort=-name&status=active");
    document.body.innerHTML = remoteTableMarkup({
      rootAttrs: 'data-om-table-sync-url="true" data-om-table-default-page-size="20" data-om-table-page-size="10"'
    });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      await component.refresh();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?page_size=10"));

      expect(window.location.pathname + window.location.search).toBe("/records?q=alpha&sort=-name&status=active");
      expect(window.history.state).toEqual(turboState);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("keeps synchronized state across a Turbo cache remount and the next refresh", async () => {
    window.history.replaceState({ turbo: { restorationIndex: 11 } }, "", "/records");
    document.body.innerHTML = `
      <form>
        <input name="q" value="beta">
        <select name="status"><option value="inactive" selected>Inactive</option></select>
      </form>
      ${remoteTableMarkup({
        rootAttrs:
          'data-om-table-sync-url="true" data-om-table-default-page-size="20" data-om-table-page-size="10"',
      })}
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const first = new Table(root);
    Object.assign(first.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await first.start();
    await first.applyFilterForm(form);
    root.querySelector<HTMLButtonElement>("[data-om-table-sort]")!.click();
    await vi.waitFor(() => expect(first.http.html).toHaveBeenCalledWith(
      "/streams?q=beta&filter.status=inactive&page_size=10&sort=name",
    ));
    root.querySelector<HTMLButtonElement>("[data-om-table-sort]")!.click();
    await vi.waitFor(() => expect(first.http.html).toHaveBeenCalledWith(
      "/streams?q=beta&filter.status=inactive&page_size=10&sort=-name",
    ));
    root.querySelector<HTMLButtonElement>("[data-om-table-page='2']")!.click();
    await vi.waitFor(() => expect(first.http.html).toHaveBeenCalledWith(
      "/streams?q=beta&filter.status=inactive&page_size=10&page=2&sort=-name",
    ));
    await first.stop();

    const restored = new Table(root);
    Object.assign(restored.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });
    await restored.start();
    try {
      root.dispatchEvent(new CustomEvent("om:table:reload"));
      await vi.waitFor(() => expect(restored.http.html).toHaveBeenCalledWith(
        "/streams?filter.status=inactive&q=beta&page_size=10&page=2&sort=-name",
      ));
      expect(window.location.pathname + window.location.search).toBe(
        "/records?q=beta&page_size=10&page=2&sort=-name&status=inactive",
      );
      expect(window.history.state).toEqual({ turbo: { restorationIndex: 11 } });
    } finally {
      await restored.stop();
      document.body.replaceChildren();
    }
  });

  it("does not add an implicit default page size to a consumer page URL", async () => {
    window.history.replaceState({ turbo: { restorationIndex: 9 } }, "", "/records?q=alpha");
    document.body.innerHTML = remoteTableMarkup({
      rootAttrs:
        'data-om-table-sync-url="true" data-om-table-default-page-size="20" data-om-table-initial-query="alpha" data-om-table-page-size="20"'
    });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      await component.refresh();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=alpha&page_size=20"));
      expect(window.location.pathname + window.location.search).toBe("/records?q=alpha");
      expect(window.history.state).toEqual({ turbo: { restorationIndex: 9 } });
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("keeps source URL behavior unless a consumer explicitly opts into URL synchronization", async () => {
    window.history.replaceState({}, "", "/records?page=2");
    document.body.innerHTML = remoteTableMarkup({
      rootAttrs: 'data-om-table-page-size="10" data-om-table-initial-page="2"'
    });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      await component.refresh();
      expect(component.http.html).toHaveBeenCalledWith("/streams?page_size=10");
      expect(window.location.search).toBe("?page=2");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("does not let data attributes rename formal remote table parameters", async () => {
    document.body.innerHTML = remoteTableMarkup({
      rootAttrs: 'data-om-table-page-size="2" data-om-table-page-size-param="limit"'
    });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    root.querySelector<HTMLButtonElement>("[data-om-table-sort]")!.setAttribute("data-om-table-sort-param", "order");
    root.querySelector<HTMLButtonElement>("[data-om-table-page='2']")!.setAttribute("data-om-table-page-param", "p");
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      root.querySelector<HTMLButtonElement>("[data-om-table-sort]")!.click();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?page_size=2&sort=name"));

      root.querySelector<HTMLButtonElement>("[data-om-table-page='2']")!.click();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?page_size=2&page=2&sort=name"));
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("builds remote URLs with initial filter data attributes", async () => {
    document.body.innerHTML = remoteTableMarkup({
      rootAttrs: 'data-om-filter-channel-id="12" data-om-filter-date-from="2026-06-01"',
    });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;
      filter.dispatchEvent(new Event("input", { bubbles: true }));

      await vi.waitFor(() =>
        expect(component.http.html).toHaveBeenCalledWith("/streams?filter.channel_id=12&filter.date_from=2026-06-01"),
      );
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("does not listen to external filter forms itself", async () => {
    document.body.innerHTML = `
      <form data-om-table-filter-form data-om-table-target="#programmes-table">
        <input name="q" value="news">
        <select name="channel_id"><option value="12" selected>BBC</option></select>
        <input name="date_from" value="2026-06-01">
        <input name="date_to" value="">
        <button type="submit">Filter</button>
      </form>
      ${remoteTableMarkup({ rootAttrs: 'id="programmes-table" data-om-table-page-size="20"' })}
    `;
    const root = document.querySelector<HTMLElement>("#programmes-table")!;
    const form = document.querySelector<HTMLFormElement>("[data-om-table-filter-form]")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

      expect(component.http.html).not.toHaveBeenCalled();
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("exposes an API for external filter forms to refresh the targeted table", async () => {
    document.body.innerHTML = `
      <form>
        <input name="q" value="news">
        <select name="channel_id"><option value="12" selected>BBC</option></select>
        <input name="date_from" value="2026-06-01">
        <input name="date_to" value="">
      </form>
      ${remoteTableMarkup({ rootAttrs: 'id="programmes-table" data-om-table-page-size="20"' })}
    `;
    const root = document.querySelector<HTMLElement>("#programmes-table")!;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      await component.applyFilterForm(form);

      expect(component.http.html).toHaveBeenCalledWith(
        "/streams?q=news&filter.channel_id=12&filter.date_from=2026-06-01&page_size=20&page=1",
      );
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("keeps official filter-prefixed external form fields unchanged", async () => {
    document.body.innerHTML = `
      <form>
        <input name="q" value="news">
        <input name="filter.channel_id" value="12">
      </form>
      ${remoteTableMarkup({ rootAttrs: 'id="programmes-table" data-om-table-page-size="20"' })}
    `;
    const root = document.querySelector<HTMLElement>("#programmes-table")!;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      await component.applyFilterForm(form);

      expect(component.http.html).toHaveBeenCalledWith(
        "/streams?q=news&filter.channel_id=12&page_size=20&page=1",
      );
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("initializes table filter forms as components and calls the target table through the manager registry", async () => {
    document.body.innerHTML = `
      <form data-om-component="table-filter-form" data-om-table-target="#programmes-table">
        <input name="q" value="news">
        <select name="channel_id"><option value="12" selected>BBC</option></select>
        <input name="date_from" value="2026-06-01">
        <input name="date_to" value="">
        <button type="submit">Filter</button>
      </form>
      ${remoteTableMarkup({ rootAttrs: 'id="programmes-table" data-om-table-page-size="20"' })}
    `;
    const registry = new ComponentRegistry();
    registry.register(TableFilterForm);
    registry.register(Table);
    const manager = new ComponentManager({ registry });

    await manager.mount(document);
    try {
      const table = manager.get<Table>("#programmes-table")!;
      Object.assign(table.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });
      document.querySelector<HTMLFormElement>("[data-om-component='table-filter-form']")!.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true })
      );

      await vi.waitFor(() =>
        expect(table.http.html).toHaveBeenCalledWith(
          "/streams?q=news&filter.channel_id=12&filter.date_from=2026-06-01&page_size=20&page=1",
        ),
      );
    } finally {
      await manager.unmount(document);
      document.body.replaceChildren();
    }
  });

  it("builds the first remote URL with the initial sort data attribute", async () => {
    document.body.innerHTML = remoteTableMarkup({
      rootAttrs: 'data-om-table-initial-sort="-name"',
    });
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      expect(root.querySelector<HTMLButtonElement>("[data-om-table-sort='name']")!.getAttribute("aria-sort")).toBe("descending");
      const filter = root.querySelector<HTMLInputElement>("[data-om-table-filter]")!;
      filter.dispatchEvent(new Event("input", { bubbles: true }));

      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?sort=-name"));
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("uses ajax source as server mode and leaves search, sort, and pagination to the backend", async () => {
    document.body.innerHTML = ajaxTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(serverTablePartialMarkup()) });

    await component.start();
    try {
      expect(visibleRowTexts(root)).toEqual(["02 Beta", "01 Alpha"]);
      expect(root.querySelectorAll<HTMLElement>("[data-om-table-page]")).toHaveLength(1);

      root.querySelector<HTMLInputElement>("[data-om-table-filter]")!.dispatchEvent(new Event("input", { bubbles: true }));
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=beta&page_size=1"));

      root.querySelector<HTMLButtonElement>("[data-om-table-sort]")!.click();
      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?q=beta&page_size=1&sort=name"));

      root.querySelector<HTMLButtonElement>("[data-om-table-page='2']")!.click();
      await vi.waitFor(() => {
        expect(component.http.html).toHaveBeenCalledWith("/streams?q=beta&page_size=1&page=2&sort=name");
        expect(visibleRowTexts(root)).toEqual(["03 Delta"]);
      });
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("uses the page size control locally and resets to the first page", async () => {
    document.body.innerHTML = pageSizeControlTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);

    await component.start();
    try {
      root.querySelector<HTMLButtonElement>("[data-om-table-page='2']")!.click();
      expect(visibleRowTexts(root)).toEqual(["02 Beta"]);

      const control = root.querySelector<HTMLSelectElement>("[data-om-table-page-size-control]")!;
      control.value = "2";
      control.dispatchEvent(new Event("change", { bubbles: true }));

      expect(visibleRowTexts(root)).toEqual(["01 Alpha", "02 Beta"]);
      expect(root.querySelector<HTMLButtonElement>("[data-om-table-page='1']")?.getAttribute("aria-current")).toBe("page");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("sends changed remote page size and resets remote pagination to page one", async () => {
    document.body.innerHTML = remotePageSizeControlMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(`<div data-om-table-partial></div>`) });

    await component.start();
    try {
      const control = root.querySelector<HTMLSelectElement>("[data-om-table-page-size-control]")!;
      control.value = "2";
      control.dispatchEvent(new Event("change", { bubbles: true }));

      await vi.waitFor(() => expect(component.http.html).toHaveBeenCalledWith("/streams?page_size=2&page=1"));
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("ignores legacy data-om-table-ajax on core table", async () => {
    document.body.innerHTML = legacyAjaxTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockResolvedValue(serverTablePartialMarkup()) });

    await component.start();
    try {
      root.querySelector<HTMLInputElement>("[data-om-table-filter]")!.dispatchEvent(new Event("input", { bubbles: true }));

      expect(component.http.html).not.toHaveBeenCalled();
      expect(visibleRowTexts(root)).toEqual(["02 Beta"]);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("shows loading and error states when remote refresh fails", async () => {
    document.body.innerHTML = remoteTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    Object.assign(component.http, { html: vi.fn().mockRejectedValue(new Error("网络错误")) });

    await component.start();

    await expect(component.refresh("/streams")).rejects.toThrow("网络错误");
    expect(root.dataset.omStatus).toBe("error");
    expect(root.querySelector<HTMLElement>("[data-om-table-loading]")!.hidden).toBe(true);
    expect(root.querySelector<HTMLElement>("[data-om-table-error]")!.hidden).toBe(false);
    expect(root.querySelector<HTMLElement>("[data-om-table-error]")!.textContent).toBe("网络错误");

    await component.stop();
    document.body.replaceChildren();
  });

  it("shows a scoped loading overlay during remote refresh", async () => {
    document.body.innerHTML = remoteTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const partial = root.querySelector<HTMLElement>("[data-om-table-partial]")!;
    const component = new Table(root);
    let resolveRefresh: (html: string) => void = () => {};
    Object.assign(component.http, {
      html: vi.fn().mockImplementation(() => new Promise<string>((resolve) => {
        resolveRefresh = resolve;
      }))
    });

    await component.start();
    const refresh = component.refresh("/streams");

    await vi.waitFor(() => {
      expect(root.dataset.omStatus).toBe("loading");
      expect(root.dataset.omPreloaderStatus).toBe("idle");
      expect(partial.dataset.omPreloaderStatus).toBe("loading");
      expect(root.querySelector("[data-om-scoped-preloader]")?.textContent).toContain("Loading...");
      expect(root.querySelector<HTMLElement>("[data-om-table-loading]")?.hidden).toBe(true);
    });

    resolveRefresh(serverTablePartialMarkup());
    await refresh;

    expect(root.dataset.omStatus).toBe("success");
    expect(partial.dataset.omPreloaderStatus).toBe("idle");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();

    await component.stop();
    document.body.replaceChildren();
  });

  it("limits remote loading overlay to the table shell when one exists", async () => {
    document.body.innerHTML = remoteTableShellMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const partial = root.querySelector<HTMLElement>("[data-om-table-partial]")!;
    const shell = root.querySelector<HTMLElement>(".om-table-shell")!;
    const component = new Table(root);
    let resolveRefresh: (html: string) => void = () => {};
    Object.assign(component.http, {
      html: vi.fn().mockImplementation(() => new Promise<string>((resolve) => {
        resolveRefresh = resolve;
      }))
    });

    await component.start();
    const refresh = component.refresh("/streams");

    await vi.waitFor(() => {
      expect(root.dataset.omStatus).toBe("loading");
      expect(root.dataset.omPreloaderStatus).toBe("idle");
      expect(partial.dataset.omPreloaderStatus).toBeUndefined();
      expect(shell.dataset.omPreloaderStatus).toBe("loading");
      expect(shell.querySelector("[data-om-scoped-preloader]")?.textContent).toContain("Loading...");
    });

    resolveRefresh(serverTablePartialMarkup());
    await refresh;

    expect(shell.dataset.omPreloaderStatus).toBe("idle");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();

    await component.stop();
    document.body.replaceChildren();
  });

  it("ignores canceled remote refreshes during lifecycle cleanup", async () => {
    document.body.innerHTML = remoteTableMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='table']")!;
    const component = new Table(root);
    const canceled = Object.assign(new Error("canceled"), { code: "ERR_CANCELED", name: "CanceledError" });
    const errorListener = vi.fn();
    root.addEventListener("om:table:error", errorListener);
    Object.assign(component.http, { html: vi.fn().mockRejectedValue(canceled) });

    await component.start();

    await expect(component.refresh("/streams")).resolves.toBeUndefined();
    expect(root.dataset.omStatus).not.toBe("error");
    expect(errorListener).not.toHaveBeenCalled();

    await component.stop();
    document.body.replaceChildren();
  });
});

/**
 * 返回包含过滤、行、空状态和分页 hook 的标准表格标记。
 */
function tableMarkup(): string {
  return `
    <section data-om-component="table">
      <input data-om-table-filter>
      <table>
        <tbody>
          <tr data-om-table-row><td>Alpha Stream</td></tr>
          <tr data-om-table-row><td>Beta Stream</td></tr>
          <tr data-om-table-row><td>Gamma Stream</td></tr>
        </tbody>
      </table>
      <p data-om-table-empty hidden></p>
      <nav>
        <button type="button" data-om-table-page="1" aria-current="page" class="active">1</button>
        <button type="button" data-om-table-page="2">2</button>
      </nav>
    </section>
  `;
}

/**
 * 返回无数据行的表格夹具，用于验证初始空状态同步。
 */
function emptyTableMarkup(): string {
  return `
    <section data-om-component="table">
      <input data-om-table-filter>
      <table>
        <tbody></tbody>
      </table>
      <p data-om-table-empty hidden></p>
    </section>
  `;
}

/**
 * 返回服务端表格首次渲染的空 shell，用于验证挂载后首刷。
 */
function remoteTableEmptyShellMarkup(): string {
  return `
    <section data-om-component="table" data-om-table-src="/streams" data-om-table-page-size="1">
      <input data-om-table-filter data-om-table-param="q">
      <div data-om-table-partial></div>
      <p data-om-table-loading hidden></p>
      <p data-om-table-error hidden></p>
    </section>
  `;
}

/**
 * 返回带初始表格骨架的服务端表格 shell，用于验证首屏占位仍会触发远程首刷。
 */
function remoteTableInitialShellMarkup(): string {
  return `
    <section data-om-component="table" data-om-table-src="/streams" data-om-table-page-size="1">
      <input data-om-table-filter data-om-table-param="q">
      <div data-om-table-partial data-om-initial-table-partial>
        <div class="om-table-shell">
          <table>
            <thead><tr><th>Name</th></tr></thead>
            <tbody data-om-table-body>
              <tr data-om-table-initial-loading><td>Loading...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <p data-om-table-loading hidden></p>
      <p data-om-table-error hidden></p>
    </section>
  `;
}

/**
 * 返回远程刷新表格夹具，包含片段、状态、搜索、排序和分页 hook。
 */
function remoteTableMarkup({ rootAttrs = "" }: { rootAttrs?: string } = {}): string {
  return `
    <section data-om-component="table" data-om-table-src="/streams" ${rootAttrs}>
      <input data-om-table-filter data-om-table-param="q">
      <button type="button" data-om-table-sort="name">Name</button>
      <div data-om-table-partial>
        <table>
          <tbody>
            <tr data-om-table-row><td>Alpha Stream</td></tr>
          </tbody>
        </table>
      </div>
      <p data-om-table-empty hidden></p>
      <p data-om-table-loading hidden></p>
      <p data-om-table-error hidden></p>
      <button type="button" data-om-table-page="2">2</button>
    </section>
  `;
}

/**
 * 返回接近后端默认模板的远程表格夹具，用于验证 loading 只覆盖表格阅读区域。
 */
function remoteTableShellMarkup(): string {
  return `
    <section data-om-component="table" data-om-table-src="/streams">
      <input data-om-table-filter data-om-table-param="q">
      <div data-om-table-partial>
        <div class="om-table-shell">
          <div class="om-table-scroll">
            <table>
              <tbody data-om-table-body>
                <tr data-om-table-row><td>Alpha Stream</td></tr>
              </tbody>
            </table>
          </div>
        </div>
        <div data-om-table-summary>Showing 1 to 1 of 1 entries</div>
        <div data-om-table-pagination><button type="button" data-om-table-page="1">1</button></div>
      </div>
      <p data-om-table-loading hidden></p>
      <p data-om-table-error hidden></p>
    </section>
  `;
}

/**
 * 返回带完整表头、tbody、summary 和 pagination 的远程表格夹具。
 */
function remoteTableWithHeadMarkup(): string {
  return `
    <section data-om-component="table" data-om-table-src="/streams">
      <div data-om-table-partial>
        <div class="table-responsive table-card">
          <table>
            <thead><tr><th class="sort sorting"><button type="button" data-om-table-sort="name">Name</button></th></tr></thead>
            <tbody data-om-table-body>
              <tr data-om-table-row><td>Alpha Stream</td></tr>
            </tbody>
          </table>
        </div>
        <div data-om-table-summary>Total 1 / 1</div>
        <div data-om-table-pagination><button type="button" data-om-table-page="1">1</button></div>
      </div>
    </section>
  `;
}

/** 返回后端 JSON 模式使用的完整 Table shell。 */
function remoteJsonTableMarkup(): string {
  return `
    <section
      data-om-component="table"
      data-om-table-src="/streams"
      data-om-table-format="json"
      data-om-table-empty-message="No streams found."
      data-om-table-page-size="10"
    >
      <input data-om-table-filter data-om-table-param="q">
      <div data-om-table-partial>
        <div class="om-table-shell">
          <table class="om-table">
            <thead><tr>
              <th data-om-column-selection data-om-column-label="Select"><input type="checkbox" data-om-table-select-all></th>
              <th data-om-column="id" data-om-column-type="integer" data-om-column-sortable="true" data-om-column-searchable="false">
                <button type="button" data-om-table-sort="id">ID</button>
              </th>
              <th data-om-column="name" data-om-column-type="string" data-om-column-sortable="true" data-om-column-searchable="true">
                <button type="button" data-om-table-sort="name">Name</button>
              </th>
            </tr></thead>
            <tbody data-om-table-body><tr data-om-table-row><td colspan="3">Existing</td></tr></tbody>
          </table>
        </div>
        <select data-om-table-page-size-control><option value="10" selected>10</option><option value="20">20</option></select>
        <div data-om-table-summary>Showing 0 to 0 of 0 entries</div>
        <div data-om-table-pagination>
          <button type="button" disabled>Previous</button>
          <button type="button" disabled>Next</button>
        </div>
      </div>
      <p data-om-table-loading hidden></p>
      <p data-om-table-error hidden></p>
    </section>
  `;
}

/** 返回与 Python Table endpoint 相同结构的 JSON payload。 */
function jsonTablePayload({
  component,
  filteredTotal,
  invalidRawValue = false,
  missingRowId = false,
  names = ["Alpha", "Beta"],
  omitCell = false,
  total
}: {
  component?: string;
  filteredTotal?: number;
  invalidRawValue?: boolean;
  missingRowId?: boolean;
  names?: string[];
  omitCell?: boolean;
  total?: number;
} = {}): Record<string, unknown> {
  const rows = names.map((name, index) => {
    const cells: Record<string, unknown> = {
      id: String(index + 1),
      name: component && index === 0
        ? `<button id="json-probe" data-om-component="${component}">${name}</button>`
        : `<strong>${name}</strong>`
    };
    if (omitCell && index === 0) delete cells.name;
    const rawValues: Record<string, unknown> = { id: index + 1, name };
    if (invalidRawValue && index === 0) rawValues.name = { invalid: true };
    return {
      cells,
      data: missingRowId && index === 0 ? {} : { id: index + 1 },
      raw_values: rawValues
    };
  });

  return {
    columns: [
      { label: "ID", name: "id", searchable: false, sortable: true, type: "integer" },
      { label: "Name", name: "name", searchable: true, sortable: true, type: "string" }
    ],
    pagination: {
      filtered_total: filteredTotal ?? rows.length,
      has_next: (filteredTotal ?? rows.length) > 10,
      page: 1,
      page_size: 10,
      total: total ?? filteredTotal ?? rows.length
    },
    rows,
    sort: ""
  };
}

/**
 * 返回 Ajax 远程表格夹具，用于验证有远程源时不执行本地过滤、排序和分页。
 */
function ajaxTableMarkup(): string {
  return `
    <section data-om-component="table" data-om-table-src="/streams" data-om-table-page-size="1">
      <input data-om-table-filter data-om-table-param="q" value="beta">
      <button type="button" data-om-table-sort="name">Name</button>
      <div data-om-table-partial>
        <table>
          <tbody>
            <tr data-om-table-row><td>02</td><td>Beta</td></tr>
            <tr data-om-table-row><td>01</td><td>Alpha</td></tr>
          </tbody>
        </table>
      </div>
      <div data-om-table-pagination>
        <button type="button" data-om-table-page="2">2</button>
      </div>
    </section>
  `;
}

/**
 * 返回带分页大小控件的本地表格夹具。
 */
function pageSizeControlTableMarkup(): string {
  return `
    <section data-om-component="table" data-om-table-page-size="1">
      <select data-om-table-page-size-control>
        <option value="1" selected>1</option>
        <option value="2">2</option>
      </select>
      <table>
        <tbody>
          <tr data-om-table-row><td>01</td><td>Alpha</td></tr>
          <tr data-om-table-row><td>02</td><td>Beta</td></tr>
          <tr data-om-table-row><td>03</td><td>Gamma</td></tr>
        </tbody>
      </table>
      <div data-om-table-pagination></div>
    </section>
  `;
}

/**
 * 返回带分页大小控件的远程表格夹具。
 */
function remotePageSizeControlMarkup(): string {
  return `
    <section data-om-component="table" data-om-table-src="/streams" data-om-table-page-size="1">
      <select data-om-table-page-size-control>
        <option value="1" selected>1</option>
        <option value="2">2</option>
      </select>
      <div data-om-table-partial>
        <table><tbody><tr data-om-table-row><td>Alpha</td></tr></tbody></table>
      </div>
    </section>
  `;
}

/**
 * 返回旧协议 Ajax 表格夹具，用于确认核心组件不再兼容旧 data-om-table-ajax。
 */
function legacyAjaxTableMarkup(): string {
  return `
    <section data-om-component="table" data-om-table-ajax="/streams" data-om-table-page-size="1">
      <input data-om-table-filter data-om-table-param="q" value="beta">
      <div data-om-table-partial>
        <table>
          <tbody>
            <tr data-om-table-row><td>02</td><td>Beta</td></tr>
            <tr data-om-table-row><td>01</td><td>Alpha</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  `;
}

/**
 * 返回服务端模式刷新后的 HTML 片段，内容故意不匹配当前搜索词。
 */
function serverTablePartialMarkup(): string {
  return `
    <div data-om-table-partial>
      <table>
        <tbody>
          <tr data-om-table-row><td>03</td><td>Delta</td></tr>
        </tbody>
      </table>
    </div>
  `;
}

/**
 * 返回服务端模式首刷后的完整 HTML 片段，包含数据区域和底部分页。
 */
function serverTablePartialWithFooterMarkup(): string {
  return `
    <div data-om-table-partial>
      <table>
        <tbody>
          <tr data-om-table-row><td>03</td><td>Delta</td></tr>
        </tbody>
      </table>
      <div data-om-table-summary>Showing 1 to 1 of 1 entries</div>
      <div data-om-table-pagination><button type="button" data-om-table-page="2">Next</button></div>
    </div>
  `;
}

/**
 * 返回支持本地排序的表格夹具。
 */
function sortableTableMarkup(): string {
  return `
    <section data-om-component="table">
      <table>
        <thead>
          <tr>
            <th class="sort sorting"><button type="button" data-om-table-sort="0">ID</button></th>
            <th class="sort sorting"><button type="button" data-om-table-sort="1">Name</button></th>
          </tr>
        </thead>
        <tbody>
          <tr data-om-table-row><td>03</td><td>Gamma</td></tr>
          <tr data-om-table-row><td>01</td><td>Alpha</td></tr>
          <tr data-om-table-row><td>02</td><td>Beta</td></tr>
        </tbody>
      </table>
    </section>
  `;
}

/**
 * 返回带列 metadata 和 raw value 的本地表格夹具。
 */
function metadataTableMarkup(): string {
  return `
    <section data-om-component="table">
      <input data-om-table-filter>
      <table>
        <thead>
          <tr>
            <th data-om-column="id" data-om-column-type="number" data-om-column-sortable="true" data-om-column-searchable="false">
              <button type="button" data-om-table-sort="id">ID</button>
            </th>
            <th data-om-column="title" data-om-column-type="string" data-om-column-sortable="true" data-om-column-searchable="true">
              <button type="button" data-om-table-sort="title">Title</button>
            </th>
            <th data-om-column="hits" data-om-column-type="number" data-om-column-sortable="true" data-om-column-searchable="false">
              <button type="button" data-om-table-sort="hits">Hits</button>
            </th>
            <th data-om-column="actions" data-om-column-type="string" data-om-column-sortable="false" data-om-column-searchable="false">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr data-om-table-row>
            <td data-om-column="id" data-raw-value="1">01</td>
            <td data-om-column="title" data-raw-value="Alpha">Alpha</td>
            <td data-om-column="hits" data-raw-value="10">10 views</td>
            <td data-om-column="actions"><button>delete alpha</button></td>
          </tr>
          <tr data-om-table-row>
            <td data-om-column="id" data-raw-value="2">02</td>
            <td data-om-column="title" data-raw-value="Beta">Beta</td>
            <td data-om-column="hits" data-raw-value="2">2 views</td>
            <td data-om-column="actions"><button>delete beta</button></td>
          </tr>
        </tbody>
      </table>
      <p data-om-table-empty hidden></p>
    </section>
  `;
}

/**
 * 返回所有列都声明为不可搜索的 metadata 表格夹具。
 */
function unsearchableMetadataTableMarkup(): string {
  return `
    <section data-om-component="table">
      <input data-om-table-filter>
      <table>
        <thead>
          <tr>
            <th data-om-column="title" data-om-column-type="string" data-om-column-sortable="true" data-om-column-searchable="false">Title</th>
            <th data-om-column="actions" data-om-column-type="string" data-om-column-sortable="false" data-om-column-searchable="false">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr data-om-table-row>
            <td data-om-column="title" data-raw-value="Alpha">Alpha</td>
            <td data-om-column="actions"><button>delete alpha</button></td>
          </tr>
          <tr data-om-table-row>
            <td data-om-column="title" data-raw-value="Beta">Beta</td>
            <td data-om-column="actions"><button>delete beta</button></td>
          </tr>
        </tbody>
      </table>
      <p data-om-table-empty hidden></p>
    </section>
  `;
}

/**
 * 返回支持过滤后批量选择的表格夹具。
 */
function selectableTableMarkup(): string {
  return `
    <section data-om-component="table">
      <input data-om-table-filter>
      <table>
        <thead>
          <tr>
            <th><input type="checkbox" data-om-table-select-all></th>
            <th>Name</th>
          </tr>
        </thead>
        <tbody>
          <tr data-om-table-row><td><input type="checkbox" data-om-table-select-row></td><td>Alpha Stream</td></tr>
          <tr data-om-table-row><td><input type="checkbox" data-om-table-select-row></td><td>Beta Stream</td></tr>
        </tbody>
      </table>
      <p data-om-table-empty hidden></p>
    </section>
  `;
}

function toolbarTableMarkup(): string {
  return `
    <section id="toolbar-table" data-om-component="table">
      <div data-om-table-toolbar>
        <span data-om-table-selection-count hidden></span>
        <div data-om-table-bulk-actions hidden><button type="button">Archive</button></div>
        <label><input type="checkbox" data-om-table-column-toggle value="name" checked> Name</label>
        <label><input type="checkbox" data-om-table-column-toggle value="hits" checked> Hits</label>
        <button type="button" data-om-table-density="comfortable" class="active" aria-pressed="true">Comfortable</button>
        <button type="button" data-om-table-density="compact" aria-pressed="false">Compact</button>
      </div>
      <table>
        <thead>
          <tr>
            <th><input type="checkbox" data-om-table-select-all></th>
            <th data-om-column="name">Name</th>
            <th data-om-column="hits">Hits</th>
          </tr>
        </thead>
        <tbody>
          <tr data-om-table-row data-om-table-row-id="1"><td><input type="checkbox" data-om-table-select-row value="1"></td><td data-om-column="name">Alpha</td><td data-om-column="hits">10</td></tr>
          <tr data-om-table-row data-om-table-row-id="2"><td><input type="checkbox" data-om-table-select-row value="2"></td><td data-om-column="name">Beta</td><td data-om-column="hits">2</td></tr>
        </tbody>
      </table>
    </section>
  `;
}

/**
 * 返回当前可见行的文本，用于断言排序结果。
 */
function visibleRowTexts(root: HTMLElement): string[] {
  return Array.from(root.querySelectorAll<HTMLTableRowElement>("[data-om-table-row]:not([hidden])")).map((row) =>
    Array.from(row.cells)
      .map((cell) => (cell.textContent || "").trim())
      .join(" ")
  );
}

/**
 * 返回可手动 resolve/reject 的 Promise，用于模拟远程请求乱序返回。
 */
function deferred<T>(): { promise: Promise<T>; reject: (error: unknown) => void; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });

  return { promise, reject, resolve };
}
