import { afterEach, describe, expect, it } from "vitest";
import { createI18n } from "../i18n";
import { CleanupRegistry } from "./cleanup";
import { ScopedPreloader } from "./preloader";

describe("ScopedPreloader", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("shows and hides a loader inside the scoped root only", () => {
    document.body.innerHTML = `<section id="scope"><p>Content</p></section><aside id="shell"></aside>`;
    const cleanup = new CleanupRegistry();
    const root = document.querySelector<HTMLElement>("#scope")!;
    const preloader = new ScopedPreloader(root, cleanup, createI18n({ locale: "en", messages: {} }));

    preloader.show("Loading channel");

    const overlay = root.querySelector<HTMLElement>("[data-om-scoped-preloader]");
    expect(root.dataset.omPreloaderStatus).toBe("loading");
    expect(overlay).not.toBeNull();
    expect(overlay?.textContent).toContain("Loading channel");
    expect(document.querySelector("#shell [data-om-scoped-preloader]")).toBeNull();

    preloader.hide();

    expect(root.dataset.omPreloaderStatus).toBe("idle");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();
  });

  it("wraps async work and hides the loader after success or failure", async () => {
    document.body.innerHTML = `<div id="scope"></div>`;
    const root = document.querySelector<HTMLElement>("#scope")!;
    const preloader = new ScopedPreloader(root, new CleanupRegistry(), createI18n({ locale: "en", messages: {} }));

    await preloader.withLoading(async () => "ok", { message: "Saving" });
    expect(root.dataset.omPreloaderStatus).toBe("idle");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();

    await expect(
      preloader.withLoading(async () => {
        throw new Error("boom");
      })
    ).rejects.toThrow("boom");
    expect(root.dataset.omPreloaderStatus).toBe("idle");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();
  });

  it("responds to scoped loading events on the root", () => {
    document.body.innerHTML = `<div id="scope"></div>`;
    const root = document.querySelector<HTMLElement>("#scope")!;
    new ScopedPreloader(root, new CleanupRegistry(), createI18n({ locale: "en", messages: {} }));

    root.dispatchEvent(new CustomEvent("om:preloader:show", { bubbles: true, detail: { message: "Filtering" } }));
    expect(root.dataset.omPreloaderStatus).toBe("loading");
    expect(root.textContent).toContain("Filtering");

    root.dispatchEvent(new CustomEvent("om:preloader:hide", { bubbles: true }));
    expect(root.dataset.omPreloaderStatus).toBe("idle");
  });

  it("removes loader DOM during cleanup", async () => {
    document.body.innerHTML = `<div id="scope"></div>`;
    const cleanup = new CleanupRegistry();
    const root = document.querySelector<HTMLElement>("#scope")!;
    const preloader = new ScopedPreloader(root, cleanup, createI18n({ locale: "en", messages: {} }));

    preloader.show();
    await cleanup.run();

    expect(root.dataset.omPreloaderStatus).toBe("idle");
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();
  });

  it("clears every scoped preloader inside a container before Turbo snapshots it", () => {
    document.body.innerHTML = `
      <main id="root" data-om-preloader-status="loading">
        <div data-om-scoped-preloader></div>
        <section data-om-preloader-status="loading">
          <div data-om-scoped-preloader></div>
        </section>
      </main>
    `;
    const root = document.querySelector<HTMLElement>("#root")!;

    ScopedPreloader.clearWithin(root);

    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();
    expect(root.dataset.omPreloaderStatus).toBe("idle");
    expect(root.querySelector<HTMLElement>("section")?.dataset.omPreloaderStatus).toBe("idle");
  });

  it("an outer scope does not take over the overlay of a nested one", () => {
    // ensureOverlay 原先用任意深度查找，而 hide() 只删直接子级：外层 show() 会接管内层
    // 已经建好的遮罩、改写它的文字，外层 hide() 再把它删掉，而内层的状态还停在 loading。
    // ScopedRoot 在构造函数里给每个 Page 和每个 Component 都建一个，所以嵌套是常态而非边角。
    document.body.innerHTML = `<div id="outer"><div id="inner"></div></div>`;
    const outer = document.querySelector<HTMLElement>("#outer")!;
    const inner = document.querySelector<HTMLElement>("#inner")!;
    const catalog = createI18n({ locale: "en", messages: {} });
    const outerPreloader = new ScopedPreloader(outer, new CleanupRegistry(), catalog);
    const innerPreloader = new ScopedPreloader(inner, new CleanupRegistry(), catalog);

    innerPreloader.show("inner message");
    outerPreloader.show("outer message");

    const overlays = Array.from(document.querySelectorAll<HTMLElement>("[data-om-scoped-preloader]"));
    expect(overlays.map((overlay) => overlay.parentElement?.id)).toEqual(["inner", "outer"]);
    expect(
      overlays.map((overlay) => overlay.querySelector("[data-om-scoped-preloader-label]")?.textContent)
    ).toEqual(["inner message", "outer message"]);

    outerPreloader.hide();

    // 内层的遮罩和状态都不该被外层的 hide() 波及。
    expect(inner.querySelector("[data-om-scoped-preloader]")).not.toBeNull();
    expect(inner.dataset.omPreloaderStatus).toBe("loading");
    expect(outer.dataset.omPreloaderStatus).toBe("idle");
  });
});
