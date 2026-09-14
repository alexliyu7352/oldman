import { describe, expect, it } from "vitest";
import { List } from "./list";

describe("List", () => {
  it("搜索和排序后端渲染的列表项", async () => {
    document.body.innerHTML = sortableListMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='list']")!;
    const component = new List(root);

    await component.start();
    try {
      const search = root.querySelector<HTMLInputElement>(".search")!;

      search.value = "jonas";
      search.dispatchEvent(new Event("input", { bubbles: true }));
      expect(visibleNames(root)).toEqual(["Jonas Arnklint"]);

      search.value = "";
      search.dispatchEvent(new Event("input", { bubbles: true }));
      root.querySelector<HTMLButtonElement>(".sort[data-sort='name']")!.click();
      expect(visibleNames(root)).toEqual(["Gustaf Lindqvist", "Jonas Arnklint", "Jonny Stromberg", "Martina Elm"]);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("支持 data 属性和 data-timestamp 字段排序", async () => {
    document.body.innerHTML = dataAttributeListMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='list']")!;
    const component = new List(root);

    await component.start();
    try {
      root.querySelector<HTMLButtonElement>("[data-om-list-sort='id']")!.click();
      expect(visibleIds(root)).toEqual(["1", "2", "3"]);

      root.querySelector<HTMLButtonElement>("[data-om-list-sort='timestamp']")!.click();
      expect(visibleNames(root)).toEqual(["Jonny Stromberg", "Jonas Arnklint", "Martina Elm"]);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("支持轻量模糊搜索", async () => {
    document.body.innerHTML = fuzzyListMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='list']")!;
    const component = new List(root);

    await component.start();
    try {
      const search = root.querySelector<HTMLInputElement>(".fuzzy-search")!;
      search.value = "gbr";
      search.dispatchEvent(new Event("input", { bubbles: true }));

      expect(visibleNames(root)).toEqual(["Guybrush Threepwood"]);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("支持本地分页和空状态", async () => {
    document.body.innerHTML = paginatedListMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='list']")!;
    const component = new List(root);

    await component.start();
    try {
      expect(visibleNames(root)).toEqual(["One", "Two"]);
      expect(root.querySelectorAll("[data-om-list-page]")).toHaveLength(2);

      root.querySelector<HTMLElement>(".pagination-next")!.click();
      expect(visibleNames(root)).toEqual(["Three"]);

      const search = root.querySelector<HTMLInputElement>(".search")!;
      search.value = "missing";
      search.dispatchEvent(new Event("input", { bubbles: true }));
      expect(root.querySelector<HTMLElement>("[data-om-list-empty]")!.hidden).toBe(false);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });
});

/**
 * 返回可搜索和排序的标准列表示例。
 */
function sortableListMarkup(): string {
  return `
    <section data-om-component="list">
      <input class="search">
      <button type="button" class="sort" data-sort="name">Sort</button>
      <ul class="list">
        <li><span class="name">Jonny Stromberg</span></li>
        <li><span class="name">Jonas Arnklint</span></li>
        <li><span class="name">Martina Elm</span></li>
        <li><span class="name">Gustaf Lindqvist</span></li>
      </ul>
    </section>
  `;
}

/**
 * 返回包含 data 属性字段的列表示例。
 */
function dataAttributeListMarkup(): string {
  return `
    <section data-om-component="list">
      <button type="button" data-om-list-sort="id">Sort ID</button>
      <button type="button" data-om-list-sort="timestamp">Sort Time</button>
      <ul class="list">
        <li data-id="3"><span class="name">Martina Elm</span><span class="timestamp" data-timestamp="34567">1986</span></li>
        <li data-id="1"><span class="name">Jonny Stromberg</span><span class="timestamp" data-timestamp="12345">1986</span></li>
        <li data-id="2"><span class="name">Jonas Arnklint</span><span class="timestamp" data-timestamp="23456">1985</span></li>
      </ul>
    </section>
  `;
}

/**
 * 返回启用模糊搜索的列表示例。
 */
function fuzzyListMarkup(): string {
  return `
    <section data-om-component="list" data-om-list-search-mode="fuzzy">
      <input class="fuzzy-search">
      <ul class="list">
        <li><span class="name">Guybrush Threepwood</span></li>
        <li><span class="name">Elaine Marley</span></li>
        <li><span class="name">LeChuck</span></li>
      </ul>
    </section>
  `;
}

/**
 * 返回带分页和空状态的列表示例。
 */
function paginatedListMarkup(): string {
  return `
    <section data-om-component="list" data-om-list-page-size="2">
      <input class="search">
      <ul class="list">
        <li><span class="name">One</span></li>
        <li><span class="name">Two</span></li>
        <li><span class="name">Three</span></li>
      </ul>
      <p data-om-list-empty hidden></p>
      <a class="pagination-prev"></a>
      <ul class="listjs-pagination"></ul>
      <a class="pagination-next"></a>
    </section>
  `;
}

/**
 * 返回当前可见列表项名称。
 */
function visibleNames(root: HTMLElement): string[] {
  return Array.from(root.querySelectorAll<HTMLElement>(".list > li:not([hidden])")).map((item) => item.querySelector(".name")?.textContent?.trim() || item.textContent?.trim() || "");
}

/**
 * 返回当前可见列表项 id。
 */
function visibleIds(root: HTMLElement): string[] {
  return Array.from(root.querySelectorAll<HTMLElement>(".list > li:not([hidden])")).map((item) => item.getAttribute("data-id") || "");
}
