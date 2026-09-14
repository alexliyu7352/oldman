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
});
