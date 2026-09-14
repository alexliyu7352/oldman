import { describe, expect, it } from "vitest";
import { CleanupRegistry } from "./cleanup";
import { AssetService } from "./assets";

describe("AssetService", () => {
  it("adds and removes stylesheet on cleanup", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    assets.stylesheet("/vendor/widget.css", { id: "widget-css", dispose: "on-unmount" });
    expect(document.querySelector("link#widget-css")).not.toBeNull();

    await cleanup.run();
    expect(document.querySelector("link#widget-css")).toBeNull();
  });

  it("keeps script when dispose is keep", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const promise = assets.script("/vendor/widget.js", { id: "widget-js", dispose: "keep" });
    const script = document.querySelector("script#widget-js");
    expect(script).toBeInstanceOf(HTMLScriptElement);
    script?.dispatchEvent(new Event("load"));

    const loadedScript = await promise;
    await cleanup.run();

    expect(loadedScript.id).toBe("widget-js");
    expect(document.querySelector("script#widget-js")).not.toBeNull();
  });

  it("applies stylesheet attributes", () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const link = assets.stylesheet("/vendor/widget.css", {
      id: "widget-css-attrs",
      media: "print",
      integrity: "sha384-test",
      crossOrigin: "anonymous",
      referrerPolicy: "no-referrer"
    });

    expect(link.media).toBe("print");
    expect(link.integrity).toBe("sha384-test");
    expect(link.crossOrigin).toBe("anonymous");
    expect(link.referrerPolicy).toBe("no-referrer");
  });

  it("applies custom stylesheet attributes without replacing core attributes", () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const link = assets.stylesheet("/vendor/widget.css", {
      id: "widget-css-custom-attrs",
      nonce: "style-nonce",
      attributes: {
        "data-page": "reports",
        disabled: true,
        href: "/unsafe.css",
        rel: "preload",
        skip: false
      }
    });

    expect(link.href).toContain("/vendor/widget.css");
    expect(link.rel).toBe("stylesheet");
    expect(link.nonce).toBe("style-nonce");
    expect(link.getAttribute("data-page")).toBe("reports");
    expect(link.hasAttribute("disabled")).toBe(true);
    expect(link.hasAttribute("skip")).toBe(false);
  });

  it("replaces an existing stylesheet with the same id when once is false", () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const first = assets.stylesheet("/vendor/theme-a.css", { id: "theme-css" });
    const second = assets.stylesheet("/vendor/theme-b.css", { id: "theme-css", once: false });

    expect(second).not.toBe(first);
    expect(document.querySelectorAll("link#theme-css")).toHaveLength(1);
    expect(document.querySelector("link#theme-css")).toBe(second);
    expect(second.href).toContain("/vendor/theme-b.css");
  });

  it("runs stylesheet remove callbacks once when assets are removed", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);
    const removed: string[] = [];

    const link = assets.stylesheet("/vendor/removable.css", {
      id: "removable-css",
      onRemove: (element) => {
        removed.push(element.id);
      }
    });

    await cleanup.run();
    expect(link.isConnected).toBe(false);
    expect(removed).toEqual(["removable-css"]);

    expect(assets.remove(link)).toBe(true);
    expect(removed).toEqual(["removable-css"]);
  });

  it("runs remove callbacks when replacing assets with the same id", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);
    const removed: string[] = [];

    const firstStylesheet = assets.stylesheet("/vendor/theme-a.css", {
      id: "replace-callback-css",
      onRemove: (element) => {
        removed.push(`css:${element.id}`);
      }
    });
    const secondStylesheet = assets.stylesheet("/vendor/theme-b.css", {
      id: "replace-callback-css",
      once: false
    });
    expect(secondStylesheet).not.toBe(firstStylesheet);

    const firstScript = assets.script("/vendor/callback-v1.js", {
      id: "replace-callback-js",
      onRemove: (element) => {
        removed.push(`js:${element.id}`);
      }
    });
    const firstScriptElement = document.querySelector<HTMLScriptElement>("#replace-callback-js");
    const firstRejected = expect(firstScript).rejects.toThrow(
      "Script load replaced before completion: /vendor/callback-v2.js"
    );
    const secondScript = assets.script("/vendor/callback-v2.js", {
      id: "replace-callback-js",
      once: false
    });
    document.querySelector<HTMLScriptElement>("#replace-callback-js")?.dispatchEvent(new Event("load"));

    await firstRejected;
    await expect(secondScript).resolves.not.toBe(firstScriptElement);
    expect(removed).toEqual(["css:replace-callback-css", "js:replace-callback-js"]);
  });

  it("loads a bundle with default attributes and page-scoped cleanup", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const bundle = assets.loadBundle({
      stylesheetDefaults: {
        nonce: "bundle-style-nonce",
        dispose: "on-unmount",
        attributes: { "data-bundle": "reports" }
      },
      scriptDefaults: {
        type: "module",
        nonce: "bundle-script-nonce",
        dispose: "on-unmount",
        attributes: { "data-bundle": "reports" }
      },
      stylesheets: [
        "/vendor/report.css",
        {
          href: "/vendor/report-theme.css",
          id: "report-theme-css",
          attributes: { "data-theme": "dark" }
        }
      ],
      scripts: [
        { src: "/vendor/report-runtime.mjs", id: "report-runtime" },
        {
          src: "/vendor/report-widget.mjs",
          id: "report-widget",
          attributes: { "data-widget": "chart" }
        }
      ]
    });

    const runtime = document.querySelector<HTMLScriptElement>("script#report-runtime");
    expect(runtime).toBeInstanceOf(HTMLScriptElement);
    expect(document.querySelector("script#report-widget")).toBeNull();
    runtime?.dispatchEvent(new Event("load"));

    await Promise.resolve();
    const widget = document.querySelector<HTMLScriptElement>("script#report-widget");
    expect(widget).toBeInstanceOf(HTMLScriptElement);
    widget?.dispatchEvent(new Event("load"));

    const result = await bundle;
    expect(result.stylesheets).toHaveLength(2);
    expect(result.scripts).toHaveLength(2);
    expect(result.stylesheets[0]?.nonce).toBe("bundle-style-nonce");
    expect(result.stylesheets[0]?.getAttribute("data-bundle")).toBe("reports");
    expect(result.stylesheets[1]?.id).toBe("report-theme-css");
    expect(result.stylesheets[1]?.getAttribute("data-bundle")).toBe("reports");
    expect(result.stylesheets[1]?.getAttribute("data-theme")).toBe("dark");
    expect(result.scripts[0]?.type).toBe("module");
    expect(result.scripts[0]?.nonce).toBe("bundle-script-nonce");
    expect(result.scripts[1]?.getAttribute("data-bundle")).toBe("reports");
    expect(result.scripts[1]?.getAttribute("data-widget")).toBe("chart");

    await cleanup.run();
    expect(document.querySelector("link[href$='report.css']")).toBeNull();
    expect(document.querySelector("link#report-theme-css")).toBeNull();
    expect(document.querySelector("script#report-runtime")).toBeNull();
    expect(document.querySelector("script#report-widget")).toBeNull();
  });

  it("can load bundled scripts in parallel", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const bundle = assets.loadBundle({
      parallelScripts: true,
      scripts: [
        { src: "/vendor/parallel-a.js", id: "parallel-a" },
        { src: "/vendor/parallel-b.js", id: "parallel-b" }
      ]
    });

    const first = document.querySelector<HTMLScriptElement>("script#parallel-a");
    const second = document.querySelector<HTMLScriptElement>("script#parallel-b");
    expect(first).toBeInstanceOf(HTMLScriptElement);
    expect(second).toBeInstanceOf(HTMLScriptElement);

    first?.dispatchEvent(new Event("load"));
    second?.dispatchEvent(new Event("load"));

    const result = await bundle;
    expect(result.scripts).toEqual([first, second]);
  });

  it("removes loaded assets explicitly by id or element", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const link = assets.stylesheet("/vendor/manual.css", { id: "manual-css", dispose: "manual" });
    const promise = assets.script("/vendor/manual.js", { id: "manual-js", dispose: "keep" });
    const script = document.querySelector<HTMLScriptElement>("script#manual-js");
    script?.dispatchEvent(new Event("load"));
    await expect(promise).resolves.toBe(script);

    expect(assets.remove("manual-css")).toBe(true);
    expect(assets.remove(script!)).toBe(true);
    expect(assets.remove("missing-asset")).toBe(false);
    expect(link.isConnected).toBe(false);
    expect(script?.isConnected).toBe(false);
  });

  it("rejects pending scripts when they are removed explicitly", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const promise = assets.script("/vendor/manual-pending.js", { id: "manual-pending" });
    const rejected = expect(promise).rejects.toThrow(
      "Script load manually removed before completion: /vendor/manual-pending.js"
    );

    expect(assets.remove("manual-pending")).toBe(true);
    expect(document.querySelector("script#manual-pending")).toBeNull();
    await rejected;
  });

  it("removes loaded bundles explicitly", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const bundle = assets.loadBundle({
      stylesheets: [{ href: "/vendor/bundle-manual.css", id: "bundle-manual-css" }],
      scripts: [{ src: "/vendor/bundle-manual.js", id: "bundle-manual-js" }]
    });
    const script = document.querySelector<HTMLScriptElement>("script#bundle-manual-js");
    script?.dispatchEvent(new Event("load"));

    const result = await bundle;
    assets.removeBundle(result);

    expect(document.querySelector("link#bundle-manual-css")).toBeNull();
    expect(document.querySelector("script#bundle-manual-js")).toBeNull();
  });

  it("loads module scripts with third-party attributes and removes them on cleanup", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const promise = assets.script("/vendor/widget.mjs", {
      id: "widget-module",
      type: "module",
      async: true,
      defer: true,
      integrity: "sha384-test",
      crossOrigin: "anonymous",
      referrerPolicy: "no-referrer",
      nonce: "script-nonce",
      attributes: {
        "data-widget": "report",
        nomodule: true,
        src: "/unsafe.js",
        type: "text/plain",
        skip: null
      },
      dispose: "on-unmount"
    });
    const script = document.querySelector("script#widget-module");
    expect(script).toBeInstanceOf(HTMLScriptElement);
    script?.dispatchEvent(new Event("load"));

    const loadedScript = await promise;

    expect(loadedScript.type).toBe("module");
    expect(loadedScript.async).toBe(true);
    expect(loadedScript.defer).toBe(true);
    expect(loadedScript.integrity).toBe("sha384-test");
    expect(loadedScript.crossOrigin).toBe("anonymous");
    expect(loadedScript.referrerPolicy).toBe("no-referrer");
    expect(loadedScript.nonce).toBe("script-nonce");
    expect(loadedScript.getAttribute("data-widget")).toBe("report");
    expect(loadedScript.hasAttribute("nomodule")).toBe(true);
    expect(loadedScript.src).toContain("/vendor/widget.mjs");
    expect(loadedScript.type).toBe("module");
    expect(loadedScript.hasAttribute("skip")).toBe(false);

    await cleanup.run();
    expect(document.querySelector("script#widget-module")).toBeNull();
  });

  it("rejects a pending page-scoped script when cleanup removes it", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const promise = assets.script("/vendor/unmounted-widget.mjs", {
      id: "unmounted-widget",
      type: "module",
      dispose: "on-unmount"
    });
    const rejected = expect(promise).rejects.toThrow(
      "Script load removed before completion: /vendor/unmounted-widget.mjs"
    );

    const script = document.querySelector("script#unmounted-widget");
    expect(script).toBeInstanceOf(HTMLScriptElement);
    await cleanup.run();

    expect(document.querySelector("script#unmounted-widget")).toBeNull();
    await rejected;
  });

  it("waits for the browser script load event before resolving", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);
    let resolved = false;

    const promise = assets.script("/vendor/late-widget.js", { id: "late-widget" });
    promise.then(() => {
      resolved = true;
    });

    await Promise.resolve();
    expect(resolved).toBe(false);

    const script = document.querySelector("script#late-widget");
    expect(script).toBeInstanceOf(HTMLScriptElement);
    script?.dispatchEvent(new Event("load"));

    await expect(promise).resolves.toBe(script);
    expect(resolved).toBe(true);
  });

  it("shares the pending script load promise for repeated id requests", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);
    let firstResolved = false;
    let secondResolved = false;

    const first = assets.script("/vendor/shared-widget.js", { id: "shared-widget" });
    const second = assets.script("/vendor/shared-widget.js", { id: "shared-widget" });

    first.then(() => {
      firstResolved = true;
    });
    second.then(() => {
      secondResolved = true;
    });

    await Promise.resolve();
    expect(document.querySelectorAll("script#shared-widget")).toHaveLength(1);
    expect(firstResolved).toBe(false);
    expect(secondResolved).toBe(false);

    const script = document.querySelector("script#shared-widget");
    expect(script).toBeInstanceOf(HTMLScriptElement);
    script?.dispatchEvent(new Event("load"));

    await expect(first).resolves.toBe(script);
    await expect(second).resolves.toBe(script);
    expect(firstResolved).toBe(true);
    expect(secondResolved).toBe(true);
  });

  it("shares pending script loads across asset service instances", async () => {
    const firstAssets = new AssetService(new CleanupRegistry());
    const secondAssets = new AssetService(new CleanupRegistry());

    const first = firstAssets.script("/vendor/cross-page-widget.js", { id: "cross-page-widget" });
    const second = secondAssets.script("/vendor/cross-page-widget.js", { id: "cross-page-widget" });

    const script = document.querySelector("script#cross-page-widget");
    expect(script).toBeInstanceOf(HTMLScriptElement);
    expect(document.querySelectorAll("script#cross-page-widget")).toHaveLength(1);
    script?.dispatchEvent(new Event("load"));

    await expect(first).resolves.toBe(script);
    await expect(second).resolves.toBe(script);
  });

  it("replaces an existing loaded script with the same id when once is false", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const first = assets.script("/vendor/widget-v1.js", { id: "replace-widget" });
    const firstScript = document.querySelector("script#replace-widget");
    expect(firstScript).toBeInstanceOf(HTMLScriptElement);
    firstScript?.dispatchEvent(new Event("load"));
    await expect(first).resolves.toBe(firstScript);

    const second = assets.script("/vendor/widget-v2.js", { id: "replace-widget", once: false });
    const secondScript = document.querySelector("script#replace-widget");
    expect(secondScript).toBeInstanceOf(HTMLScriptElement);
    expect(secondScript).not.toBe(firstScript);
    expect(document.querySelectorAll("script#replace-widget")).toHaveLength(1);
    expect((secondScript as HTMLScriptElement).src).toContain("/vendor/widget-v2.js");

    secondScript?.dispatchEvent(new Event("load"));
    await expect(second).resolves.toBe(secondScript);
  });

  it("rejects a pending script load when once false replaces it", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const first = assets.script("/vendor/pending-v1.js", { id: "pending-replace-widget" });
    const firstScript = document.querySelector("script#pending-replace-widget");
    expect(firstScript).toBeInstanceOf(HTMLScriptElement);
    const firstRejected = expect(first).rejects.toThrow(
      "Script load replaced before completion: /vendor/pending-v2.js"
    );

    const second = assets.script("/vendor/pending-v2.js", {
      id: "pending-replace-widget",
      once: false
    });
    const secondScript = document.querySelector("script#pending-replace-widget");

    expect(secondScript).toBeInstanceOf(HTMLScriptElement);
    expect(secondScript).not.toBe(firstScript);
    expect(document.querySelectorAll("script#pending-replace-widget")).toHaveLength(1);
    await firstRejected;

    secondScript?.dispatchEvent(new Event("load"));
    await expect(second).resolves.toBe(secondScript);
  });

  it("removes failed scripts by default so repeated id requests can retry", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const failed = assets.script("/vendor/retry-widget.js", { id: "retry-widget" });
    const failedScript = document.querySelector("script#retry-widget");
    expect(failedScript).toBeInstanceOf(HTMLScriptElement);
    failedScript?.dispatchEvent(new Event("error"));

    await expect(failed).rejects.toThrow("Failed to load script: /vendor/retry-widget.js");
    expect(document.querySelector("script#retry-widget")).toBeNull();

    const retry = assets.script("/vendor/retry-widget.js", { id: "retry-widget" });
    const retryScript = document.querySelector("script#retry-widget");
    expect(retryScript).toBeInstanceOf(HTMLScriptElement);
    expect(retryScript).not.toBe(failedScript);

    let retried = false;
    retry.then(() => {
      retried = true;
    });

    await Promise.resolve();
    expect(retried).toBe(false);

    retryScript?.dispatchEvent(new Event("load"));
    await expect(retry).resolves.toBe(retryScript);
    expect(retried).toBe(true);
  });

  it("replaces failed scripts on retry even when removeOnError is disabled", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const failed = assets.script("/vendor/manual-error-widget.js", {
      id: "manual-error-widget",
      removeOnError: false
    });
    const failedScript = document.querySelector("script#manual-error-widget");
    expect(failedScript).toBeInstanceOf(HTMLScriptElement);
    failedScript?.dispatchEvent(new Event("error"));

    await expect(failed).rejects.toThrow("Failed to load script: /vendor/manual-error-widget.js");
    expect(document.querySelector("script#manual-error-widget")).toBe(failedScript);

    const retry = assets.script("/vendor/manual-error-widget.js", { id: "manual-error-widget" });
    const retryScript = document.querySelector("script#manual-error-widget");
    expect(retryScript).toBeInstanceOf(HTMLScriptElement);
    expect(retryScript).not.toBe(failedScript);

    retryScript?.dispatchEvent(new Event("load"));
    await expect(retry).resolves.toBe(retryScript);
  });

  it("rejects when the browser reports a script load error", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);

    const promise = assets.script("/vendor/missing-widget.js", { id: "missing-widget" });
    document.querySelector("script#missing-widget")?.dispatchEvent(new Event("error"));

    await expect(promise).rejects.toThrow("Failed to load script: /vendor/missing-widget.js");
    expect(document.querySelector("script#missing-widget")).toBeNull();
  });

  it("runs script remove callbacks when failed scripts are removed", async () => {
    const cleanup = new CleanupRegistry();
    const assets = new AssetService(cleanup);
    const removed: string[] = [];

    const promise = assets.script("/vendor/missing-callback-widget.js", {
      id: "missing-callback-widget",
      onRemove: (element) => {
        removed.push(element.id);
      }
    });
    document.querySelector("script#missing-callback-widget")?.dispatchEvent(new Event("error"));

    await expect(promise).rejects.toThrow("Failed to load script: /vendor/missing-callback-widget.js");
    expect(document.querySelector("script#missing-callback-widget")).toBeNull();
    expect(removed).toEqual(["missing-callback-widget"]);
  });
});
