import { describe, expect, it } from "vitest";
import { page, setupPage } from "./setup-page";
import { Page } from "./page";
import { PageRegistry } from "./registry";

describe("page", () => {
  it("registers class-based pages by server-rendered page name", async () => {
    document.body.innerHTML = `<main data-om-page="class-setup"></main>`;

    class ClassSetupPage extends Page {
      async mount(): Promise<void> {
        this.root.dataset.classSetup = "mounted";
      }
    }

    setupPage("class-setup", ClassSetupPage);

    const registry = new PageRegistry();
    const instance = await registry.mount(document);

    expect(instance).toBeInstanceOf(ClassSetupPage);
    expect(document.querySelector<HTMLElement>("[data-om-page]")?.dataset.classSetup).toBe("mounted");

    await registry.unmount();
  });

  it("provides the same core services as class pages", async () => {
    document.body.innerHTML = `
      <main data-om-page="setup">
        <button data-refresh>Refresh</button>
      </main>
    `;

    const calls: string[] = [];
    let setupSignal: AbortSignal | undefined;
    page("setup", (context) => {
      setupSignal = context.signal;
      calls.push(context.state);
      context.on("click", "[data-refresh]", () => calls.push("click"));
      context.onCustom<{ value: string }>("om:setup:refresh", "[data-refresh]", (event) =>
        calls.push(event.detail.value)
      );
      context.listen(window, "resize", () => calls.push("resize"));
      context.listen<CustomEvent<{ value: string }>>(context.root, "om:setup:local", (event) => {
        calls.push(event.detail.value);
      });
      context.emit("om:setup:ready", { state: context.state });
      calls.push(typeof context.runAction);
      context.onCoreEvent("om:action:success", (event) => {
        calls.push(event.detail.response.message);
      });
      calls.push(context.$("[data-refresh]").textContent ?? "");
      calls.push(String(context.$$("[data-refresh]").length));
      context.cleanup(() => {
        calls.push("cleanup");
      });

      expect(context.http).toBeDefined();
      expect(context.assets).toBeDefined();
      expect(context.transitions).toBeDefined();
      context.preferences.set("setup.ready", "true");
      expect(context.preferences.get("setup.ready")).toBe("true");
      context.preferences.remove("setup.ready");
      expect(context.signal.aborted).toBe(false);
    });

    const ready: CustomEvent[] = [];
    document
      .querySelector<HTMLElement>("[data-om-page]")!
      .addEventListener("om:setup:ready", (event) => ready.push(event as CustomEvent));
    const registry = new PageRegistry();
    const instance = await registry.mount(document);
    window.dispatchEvent(new Event("resize"));
    document
      .querySelector<HTMLElement>("[data-om-page]")!
      .dispatchEvent(new CustomEvent("om:setup:local", { bubbles: true, detail: { value: "local" } }));
    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    document
      .querySelector("button")!
      .dispatchEvent(new CustomEvent("om:setup:refresh", { bubbles: true, detail: { value: "custom" } }));
    document.querySelector("button")!.dispatchEvent(
      new CustomEvent("om:action:success", {
        bubbles: true,
        detail: {
          method: "post",
          params: {},
          response: { error_code: 0, message: "action", data: {}, actions: [] },
          trigger: document.querySelector("button")!,
          url: "/actions"
        }
      })
    );
    await registry.unmount();
    expect(setupSignal?.aborted).toBe(true);
    window.dispatchEvent(new Event("resize"));
    document
      .querySelector<HTMLElement>("[data-om-page]")!
      .dispatchEvent(new CustomEvent("om:setup:local", { bubbles: true, detail: { value: "late" } }));
    document.querySelector("button")!.dispatchEvent(
      new CustomEvent("om:action:success", {
        bubbles: true,
        detail: {
          method: "post",
          params: {},
          response: { error_code: 0, message: "late", data: {}, actions: [] },
          trigger: document.querySelector("button")!,
          url: "/actions"
        }
      })
    );

    expect(instance?.state).toBe("unmounted");
    expect(ready[0]?.detail).toEqual({ state: "mounting" });
    expect(calls).toEqual([
      "mounting",
      "function",
      "Refresh",
      "1",
      "resize",
      "local",
      "click",
      "custom",
      "action",
      "cleanup"
    ]);
  });

  it("provides transition helpers in setup callbacks", async () => {
    document.body.innerHTML = `
      <main data-om-page="setup-transitions">
        <section id="panel" hidden></section>
        <button id="toggle"></button>
      </main>
    `;

    const calls: string[] = [];
    page("setup-transitions", async ({ $, show, hide, toggle, withClasses, toggleClass }) => {
      const panel = $("#panel");
      const button = $("#toggle");

      await show(panel, "none");
      calls.push(panel.hidden ? "hidden" : "shown");
      await hide(panel, "none");
      calls.push(panel.hidden ? "hidden" : "shown");
      await toggle(panel, undefined, "none");
      calls.push(panel.hidden ? "hidden" : "shown");
      calls.push(String(toggleClass(button, "is-active", true)));
      void withClasses(panel, ["is-loading"], async () => new Promise<void>(() => {}));
    });

    const registry = new PageRegistry();
    await registry.mount(document);

    const panel = document.querySelector<HTMLElement>("#panel")!;
    const button = document.querySelector<HTMLElement>("#toggle")!;

    expect(calls).toEqual(["shown", "hidden", "shown", "true"]);
    expect(panel.classList.contains("is-loading")).toBe(true);
    expect(button.classList.contains("is-active")).toBe(true);

    await registry.unmount();
    expect(panel.classList.contains("is-loading")).toBe(false);
  });

  it("provides asset helpers in setup callbacks", async () => {
    document.body.innerHTML = `<main data-om-page="setup-assets"></main>`;

    const calls: string[] = [];
    page("setup-assets", async ({ loadAssets, loadScript, loadStylesheet, removeAsset, removeAssets }) => {
      const stylesheet = loadStylesheet("/static/setup.css", {
        id: "setup-css",
        dispose: "on-unmount"
      });
      calls.push(stylesheet.id);

      const scriptPromise = loadScript("/static/setup.js", {
        id: "setup-widget",
        dispose: "on-unmount"
      });
      document.querySelector<HTMLScriptElement>("#setup-widget")?.dispatchEvent(new Event("load"));
      const script = await scriptPromise;
      calls.push(script.id);

      const bundlePromise = loadAssets({
        stylesheets: [{ href: "/static/setup-preview.css", id: "setup-preview-css", dispose: "manual" }],
        scripts: [{ src: "/static/setup-preview.js", id: "setup-preview-widget", dispose: "manual" }]
      });
      document.querySelector<HTMLScriptElement>("#setup-preview-widget")?.dispatchEvent(new Event("load"));
      const bundle = await bundlePromise;
      removeAssets(bundle);
      calls.push(String(removeAsset("missing-asset")));
    });

    const registry = new PageRegistry();
    await registry.mount(document);

    expect(calls).toEqual(["setup-css", "setup-widget", "false"]);
    expect(document.querySelector("#setup-css")).toBeInstanceOf(HTMLLinkElement);
    expect(document.querySelector("#setup-widget")).toBeInstanceOf(HTMLScriptElement);
    expect(document.querySelector("#setup-preview-css")).toBeNull();
    expect(document.querySelector("#setup-preview-widget")).toBeNull();

    await registry.unmount();
    expect(document.querySelector("#setup-css")).toBeNull();
    expect(document.querySelector("#setup-widget")).toBeNull();
  });
});
