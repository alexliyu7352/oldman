import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPreferenceStore, PreferenceStore } from "./preferences";

describe("PreferenceStore", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    for (const cookie of document.cookie.split(";")) {
      const name = cookie.split("=")[0]?.trim();
      if (name) document.cookie = `${name}=; Max-Age=0; Path=/`;
    }
  });

  it("stores string values in localStorage with an oldman namespace by default", () => {
    const store = createPreferenceStore();

    store.set("sidebar", "collapsed");

    expect(window.localStorage.getItem("oldman:sidebar")).toBe("collapsed");
    expect(store.get("sidebar")).toBe("collapsed");
  });

  it("supports custom namespaces and sessionStorage", () => {
    const store = new PreferenceStore({
      backend: "session",
      namespace: "admin"
    });

    store.set("theme", "dark");

    expect(window.sessionStorage.getItem("admin:theme")).toBe("dark");
    expect(store.get("theme")).toBe("dark");

    store.remove("theme");
    expect(store.get("theme")).toBeNull();
  });

  it("stores JSON values and updates them atomically", () => {
    const store = createPreferenceStore({ backend: "memory" });

    store.setJson("table", {
      columns: ["actor"],
      pageSize: 25
    });

    expect(store.getJson<{ columns: string[]; pageSize: number }>("table")).toEqual({
      columns: ["actor"],
      pageSize: 25
    });

    const next = store.updateJson<{ columns: string[]; pageSize: number }>("table", (current) => ({
      columns: current?.columns ?? [],
      pageSize: 50
    }));

    expect(next).toEqual({
      columns: ["actor"],
      pageSize: 50
    });
    expect(store.getJson("table")).toEqual({
      columns: ["actor"],
      pageSize: 50
    });
  });

  it("returns provided JSON fallbacks and removes when an update returns null", () => {
    const store = createPreferenceStore({ backend: "memory" });

    store.set("broken", "{");
    expect(store.getJson("broken", { ok: true })).toEqual({ ok: true });

    store.setJson("filters", { q: "alex" });
    const next = store.updateJson<{ q: string }>("filters", () => null);

    expect(next).toBeNull();
    expect(store.get("filters")).toBeNull();
  });

  it("can persist preferences as cookies", () => {
    const store = createPreferenceStore({
      backend: "cookie",
      cookie: {
        path: "/"
      },
      namespace: "prefs"
    });

    store.set("locale", "zh-CN");
    expect(store.get("locale")).toBe("zh-CN");

    store.remove("locale");
    expect(store.get("locale")).toBeNull();
  });

  it("falls back to in-memory storage when a browser storage backend throws", () => {
    const storage: Storage = {
      get length() {
        return 0;
      },
      clear: vi.fn(),
      getItem: vi.fn(() => {
        throw new Error("blocked");
      }),
      key: vi.fn(() => null),
      removeItem: vi.fn(() => {
        throw new Error("blocked");
      }),
      setItem: vi.fn(() => {
        throw new Error("blocked");
      })
    };
    const store = createPreferenceStore({
      backend: storage,
      namespace: ""
    });

    store.set("sidebar", "collapsed");

    expect(store.get("sidebar")).toBe("collapsed");

    store.remove("sidebar");
    expect(store.get("sidebar")).toBeNull();
  });
});
