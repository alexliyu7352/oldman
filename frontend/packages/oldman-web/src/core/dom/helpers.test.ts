import { describe, expect, it, vi } from "vitest";
import {
  addDomParam,
  collectElementParams,
  collectFormParams,
  collectIncludedParams,
  attr,
  closest,
  data,
  delegate,
  mustQuery,
  query,
  queryAllSelfOrDescendants,
  querySelfOrDescendant,
  setClasses,
  setHidden
} from "./helpers";

describe("DOM helpers", () => {
  it("queries optional and required elements inside a root", () => {
    document.body.innerHTML = `<main><button data-save>Save</button></main>`;
    const root = document.querySelector("main")!;

    expect(query(root, "[data-save]")).toBeInstanceOf(HTMLButtonElement);
    expect(query(root, "[data-missing]")).toBeNull();
    expect(mustQuery(root, "[data-save]")).toBeInstanceOf(HTMLButtonElement);
    expect(() => mustQuery(root, "[data-missing]")).toThrow("Element not found: [data-missing]");
  });

  it("queries a matching root before falling back to descendants", () => {
    document.body.innerHTML = `<main id="root"><button data-save>Save</button></main>`;
    const root = document.querySelector("main")!;

    expect(querySelfOrDescendant(root, "#root")).toBe(root);
    expect(querySelfOrDescendant(root, "[data-save]")).toBeInstanceOf(HTMLButtonElement);
    expect(querySelfOrDescendant(root, "[data-missing]")).toBeNull();
  });

  it("queries all matching roots and descendants", () => {
    document.body.innerHTML = `<main data-panel><section data-panel></section><section data-panel></section></main>`;
    const root = document.querySelector("main")!;

    expect(queryAllSelfOrDescendants(root, "[data-panel]")).toEqual([
      root,
      ...Array.from(root.querySelectorAll("[data-panel]"))
    ]);
  });

  it("reads typed data attributes with fallback values", () => {
    document.body.innerHTML = `
      <button
        data-page="2"
        data-page-size="25"
        data-enabled="true"
        data-empty=""
        data-tags="active, archived, pending"
        data-config='{"page":2,"filters":["active"]}'
        data-invalid-json="{"
      ></button>
    `;
    const button = document.querySelector("button")!;

    expect(data(button, "page")).toBe("2");
    expect(data.string(button, "page")).toBe("2");
    expect(data(button, "page-size")).toBe("25");
    expect(data(button, "missing", "fallback")).toBe("fallback");
    expect(data.number(button, "page")).toBe(2);
    expect(data.integer(button, "page-size")).toBe(25);
    expect(data.integer(button, "missing", 10)).toBe(10);
    expect(data.number(button, "missing", 1)).toBe(1);
    expect(data.boolean(button, "enabled")).toBe(true);
    expect(data.boolean(button, "empty", true)).toBe(false);
    expect(data.list(button, "tags")).toEqual(["active", "archived", "pending"]);
    expect(data.list(button, "missing", ["fallback"])).toEqual(["fallback"]);
    expect(data.json<{ page: number; filters: string[] }>(button, "config")).toEqual({
      filters: ["active"],
      page: 2
    });
    expect(data.json(button, "invalid-json", { ok: false })).toEqual({ ok: false });
  });

  it("sets attributes, classes, and hidden state", () => {
    const element = document.createElement("section");

    attr(element, "aria-busy", "true");
    attr(element, "aria-label", null);
    setClasses(element, { active: true, disabled: false });
    setHidden(element, true);

    expect(element.getAttribute("aria-busy")).toBe("true");
    expect(element.hasAttribute("aria-label")).toBe(false);
    expect(element.className).toBe("active");
    expect(element.hidden).toBe(true);
    expect(element.getAttribute("aria-hidden")).toBe("true");
  });

  it("delegates events and returns cleanup", () => {
    document.body.innerHTML = `<div id="root"><button data-save>Save</button></div>`;
    const root = document.querySelector<HTMLElement>("#root")!;
    const handler = vi.fn();

    const stop = delegate(root, "click", "[data-save]", handler);
    root.querySelector("button")!.click();
    stop();
    root.querySelector("button")!.click();

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0]![1]).toBe(root.querySelector("button"));
  });

  it("finds closest matches within an optional boundary", () => {
    document.body.innerHTML = `<section><div><button>Save</button></div></section>`;
    const section = document.querySelector("section")!;
    const button = document.querySelector("button")!;

    expect(closest(button, "section")).toBe(section);
    expect(closest(button, "body", section)).toBeNull();
  });

  it("collects form and included element params with native control semantics", () => {
    document.body.innerHTML = `
      <main id="page">
        <form id="filters">
          <input name="q" value="audit">
          <input name="ignored" value="disabled" disabled>
          <input type="checkbox" name="segment" value="paid" checked>
          <input type="checkbox" name="segment" value="free">
          <input type="radio" name="state" value="open" checked>
          <input type="radio" name="state" value="closed">
          <button name="page" value="2">Search</button>
        </form>
        <select id="regions" name="region" multiple>
          <option value="us" selected>US</option>
          <option value="eu" selected>EU</option>
          <option value="apac">APAC</option>
        </select>
        <input id="token" name="token" value="abc">
        <input id="off" type="checkbox" name="off" value="1">
      </main>
    `;
    const root = document.querySelector<HTMLElement>("#page")!;
    const form = document.querySelector<HTMLFormElement>("#filters")!;
    const button = document.querySelector<HTMLButtonElement>("button")!;

    expect(collectFormParams(form, { submitter: button })).toEqual({
      q: "audit",
      segment: "paid",
      state: "open",
      page: "2"
    });
    expect(collectElementParams(document.querySelector<HTMLElement>("#regions")!)).toEqual({
      region: ["us", "eu"]
    });
    expect(collectIncludedParams(root, "#filters, #regions, #token, #off")).toEqual({
      q: "audit",
      segment: "paid",
      state: "open",
      region: ["us", "eu"],
      token: "abc"
    });
    expect(collectIncludedParams(form, "#filters")).toEqual({
      q: "audit",
      segment: "paid",
      state: "open"
    });
    expect(collectIncludedParams(document.querySelector<HTMLElement>("#token")!, "#token")).toEqual({
      token: "abc"
    });
  });

  it("appends repeated DOM params as arrays", () => {
    const params = {};

    addDomParam(params, "tag", "admin");
    addDomParam(params, "tag", "audit");

    expect(params).toEqual({ tag: ["admin", "audit"] });
  });
});
