import { type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { describe, expect, it, vi } from "vitest";
import { Component } from "../component/component";
import { globalComponentRegistry } from "../component/registry";
import type { HttpClient } from "../http/client";
import { createOldmanContext, resetOldmanContext, setOldmanContext } from "../runtime/context";
import { Page } from "./page";
import { PageRegistry } from "./registry";

function response(config: InternalAxiosRequestConfig, data: unknown): AxiosResponse {
  return {
    data,
    status: 200,
    statusText: "OK",
    headers: {},
    config,
    request: {}
  };
}

class AuditPage extends Page {
  static pageName = "admin-audit";
  readonly calls: string[] = [];

  async beforeMount() {
    this.calls.push("beforeMount");
  }

  async mount() {
    this.calls.push("mount");
    this.on("click", "[data-refresh]", () => {
      this.calls.push("click");
    });
    this.onCustom<{ value: string }>("om:audit:refresh", "[data-refresh]", (event) => {
      this.calls.push(event.detail.value);
    });
    this.onCoreEvent("om:action:success", (event) => {
      this.calls.push(event.detail.response.message);
    });
  }

  async afterMount() {
    this.calls.push("afterMount");
  }

  async beforeUnmount() {
    this.calls.push("beforeUnmount");
  }

  async unmount() {
    this.calls.push("unmount");
  }
}

class ActionPage extends Page {
  static pageName = "action-page";

  async mount() {
    this.http.requestJson = vi.fn().mockResolvedValue({
      error_code: 0,
      message: "",
      data: {},
      actions: [{ action: "replace_html", html: "<div id=\"row\">new</div>" }]
    });

    await this.runAction(this.$("[data-om-action]"));
  }
}

class SubmitterActionPage extends Page {
  static pageName = "submitter-action-page";
  readonly calls: unknown[][] = [];

  async mount() {
    this.http.requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      this.calls.push(args);
      return {
        error_code: 0,
        message: "",
        data: {},
        actions: [{ action: "replace_html", html: "<div id=\"row\">draft</div>" }]
      } as T;
    };

    await this.runAction(this.$("form"), {
      submitter: this.$("button")
    });
  }
}

class EventPage extends Page {
  static pageName = "event-page";
  readonly calls: string[] = [];

  async mount() {
    this.listen(window, "resize", () => {
      this.calls.push("resize");
    });
    this.listen<CustomEvent<{ value: string }>>(this.root, "om:event-page:local", (event) => {
      this.calls.push(event.detail.value);
    });
    this.emit("om:event-page:ready", { state: this.state });
  }
}

class TransitionPage extends Page {
  static pageName = "transition-page";
  readonly calls: string[] = [];

  async mount() {
    const panel = this.$("#panel");
    const button = this.$("#toggle");

    await this.show(panel, "none");
    this.calls.push(panel.hidden ? "hidden" : "shown");
    await this.hide(panel, "none");
    this.calls.push(panel.hidden ? "hidden" : "shown");
    await this.toggle(panel, undefined, "none");
    this.calls.push(panel.hidden ? "hidden" : "shown");
    this.calls.push(String(this.toggleClass(button, "is-active", true)));
    void this.withClasses(panel, ["is-loading"], async () => new Promise<void>(() => {}));
  }
}

class AssetPage extends Page {
  static pageName = "asset-page";
  readonly calls: string[] = [];

  async mount() {
    const stylesheet = this.loadStylesheet("/static/report.css", {
      id: "report-css",
      dispose: "on-unmount",
      onRemove: (element) => {
        this.calls.push(`${element.id}:removed`);
      }
    });
    this.calls.push(stylesheet.id);

    const scriptPromise = this.loadScript("/static/report-widget.js", {
      id: "report-widget",
      dispose: "on-unmount",
      onRemove: (element) => {
        this.calls.push(`${element.id}:removed`);
      }
    });
    document.querySelector<HTMLScriptElement>("#report-widget")?.dispatchEvent(new Event("load"));
    const script = await scriptPromise;
    this.calls.push(script.id);

    const bundlePromise = this.loadAssets({
      stylesheetDefaults: {
        dispose: "manual"
      },
      scriptDefaults: {
        dispose: "manual"
      },
      stylesheets: [{ href: "/static/preview.css", id: "preview-css" }],
      scripts: [{ src: "/static/preview.js", id: "preview-widget" }]
    });
    document.querySelector<HTMLScriptElement>("#preview-widget")?.dispatchEvent(new Event("load"));
    const bundle = await bundlePromise;
    this.calls.push(String(bundle.stylesheets.length + bundle.scripts.length));
    this.removeAssets(bundle);
    this.calls.push(String(this.removeAsset("missing-asset")));
  }
}

class PreferencePage extends Page {
  static pageName = "preference-page";

  async mount() {
    this.preferences.set("audit.pageSize", "50");
  }
}

class NestedComponent extends Component {
  static componentName = "nested";
  static mounted = 0;
  static unmounted = 0;

  /**
   * 记录页面作用域组件管理器已经挂载该组件。
   */
  async mount() {
    NestedComponent.mounted += 1;
  }

  async unmount() {
    NestedComponent.unmounted += 1;
  }
}

class TestPage extends Page {
  static pageName = "test-page";

  async mount() {
    this.components.register("nested", NestedComponent);
    await this.components.mount(this.root);
  }
}

class GlobalPageComponent extends Component {
  static componentName = "global-page-component";
  static mounted = 0;
  static unmounted = 0;

  async mount() {
    GlobalPageComponent.mounted += 1;
  }

  async unmount() {
    GlobalPageComponent.unmounted += 1;
  }
}

class GlobalComponentPage extends Page {
  static pageName = "global-component-page";

  async mount() {
    await this.components.mount(this.root);
  }
}

class FailingUnmountComponent extends Component {
  static componentName = "failing-unmount";
  static calls: string[] = [];

  async unmount() {
    FailingUnmountComponent.calls.push(this.root.id);
    throw new Error(`component unmount failed: ${this.root.id}`);
  }
}

class SuccessfulUnmountComponent extends Component {
  static componentName = "successful-unmount";
  static calls: string[] = [];

  async unmount() {
    SuccessfulUnmountComponent.calls.push(this.root.id);
  }
}

class FailingComponentPage extends Page {
  static pageName = "failing-component-page";

  async mount() {
    this.components.register("failing-unmount", FailingUnmountComponent);
    this.components.register("successful-unmount", SuccessfulUnmountComponent);
    await this.components.mount(this.root);
  }
}

describe("PageRegistry", () => {
  it("exposes scoped preloaders for page root and child containers", async () => {
    class PreloaderPage extends Page {}

    document.body.innerHTML = `<main id="main"><section id="child"></section></main>`;
    const root = document.querySelector<HTMLElement>("#main")!;
    const child = document.querySelector<HTMLElement>("#child")!;
    const page = new PreloaderPage(root);

    page.preloader.show("Loading page");
    expect(root.querySelector("[data-om-scoped-preloader]")?.textContent).toContain("Loading page");

    const childPreloader = page.createPreloader(child);
    childPreloader.show("Loading child");
    expect(child.querySelector("[data-om-scoped-preloader]")?.textContent).toContain("Loading child");

    await page.runCleanup();
    expect(root.querySelector("[data-om-scoped-preloader]")).toBeNull();
    expect(child.querySelector("[data-om-scoped-preloader]")).toBeNull();
  });

  it("mounts matching data-om-page and unmounts with cleanup", async () => {
    document.body.innerHTML = `
      <main data-om-page="admin-audit">
        <button data-refresh>Refresh</button>
      </main>
    `;

    const registry = new PageRegistry();
    registry.register(AuditPage);

    const instance = await registry.mount(document);
    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    document
      .querySelector("button")!
      .dispatchEvent(new CustomEvent("om:audit:refresh", { bubbles: true, detail: { value: "custom" } }));
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
    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    document
      .querySelector("button")!
      .dispatchEvent(new CustomEvent("om:audit:refresh", { bubbles: true, detail: { value: "late" } }));
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

    expect(instance).toBeInstanceOf(AuditPage);
    expect((instance as AuditPage).calls).toEqual([
      "beforeMount",
      "mount",
      "afterMount",
      "click",
      "custom",
      "action",
      "beforeUnmount",
      "unmount"
    ]);
  });

  it("mounts a matching scoped root page element", async () => {
    document.body.innerHTML = `<main id="audit-page" data-om-page="admin-audit"></main>`;
    const root = document.querySelector<HTMLElement>("#audit-page")!;
    const registry = new PageRegistry();
    registry.register(AuditPage);

    const instance = await registry.mount(root);

    expect(instance).toBeInstanceOf(AuditPage);
    expect(instance?.root).toBe(root);
    await registry.unmount();
  });

  it("aborts page-scoped default http requests on unmount", async () => {
    let requestSignal: AbortSignal | undefined;
    let pageSignal: AbortSignal | undefined;

    class HttpPage extends Page {
      static pageName = "http-page";

      async mount() {
        pageSignal = this.signal;
        const adapter: AxiosAdapter = async (config) => {
          requestSignal = config.signal as AbortSignal | undefined;
          return response(config, { ok: true });
        };

        await this.http.getJson("/slow", { adapter });
      }
    }

    document.body.innerHTML = `<main data-om-page="http-page"></main>`;
    const registry = new PageRegistry();
    registry.register(HttpPage);

    await registry.mount(document);
    expect(requestSignal?.aborted).toBe(false);
    expect(pageSignal?.aborted).toBe(false);
    expect(requestSignal).toBe(pageSignal);

    await registry.unmount();
    expect(requestSignal?.aborted).toBe(true);
    expect(pageSignal?.aborted).toBe(true);
  });

  it("runs data actions through the page-scoped helpers", async () => {
    document.body.innerHTML = `
      <main data-om-page="action-page">
        <button data-om-action="post" data-om-url="/disable" data-om-target="#row" data-om-swap="outer">
          Disable
        </button>
        <div id="row">old</div>
      </main>
    `;

    const registry = new PageRegistry();
    setOldmanContext(createOldmanContext({ pageRegistry: registry }));
    registry.register(ActionPage);
    try {
      await registry.mount(document);
      expect(document.querySelector("#row")!.textContent).toBe("new");
    } finally {
      await registry.unmount();
      resetOldmanContext();
    }
  });

  it("passes submitters through page-scoped form actions", async () => {
    document.body.innerHTML = `
      <main data-om-page="submitter-action-page">
        <form data-om-action="post" action="/users" data-om-target="#row">
          <input name="display_name" required>
          <button name="intent" value="draft" formaction="/users/draft" formmethod="get" formnovalidate>
            Save draft
          </button>
        </form>
        <div id="row">old</div>
      </main>
    `;

    const registry = new PageRegistry();
    setOldmanContext(createOldmanContext({ pageRegistry: registry }));
    registry.register(SubmitterActionPage);
    try {
      const instance = (await registry.mount(document)) as SubmitterActionPage;
      expect(document.querySelector("#row")!.textContent).toBe("draft");
      const [method, url, data, config] = instance.calls[0]!;
      expect(method).toBe("get");
      expect(url).toBe("/users/draft");
      expect(data).toBeUndefined();
      expect(Array.from((config as { params: URLSearchParams }).params.entries())).toEqual([
        ["display_name", ""],
        ["intent", "draft"]
      ]);
    } finally {
      await registry.unmount();
      resetOldmanContext();
    }
  });

  it("queries one or many elements inside the page root", () => {
    document.body.innerHTML = `
      <main data-om-page="admin-audit">
        <button data-filter>Active</button>
        <button data-filter>Archived</button>
      </main>
      <button data-filter>Outside</button>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    const page = new AuditPage(root);

    expect(page.$("[data-om-page]")).toBe(root);
    expect(page.$("[data-filter]").textContent).toBe("Active");
    expect(page.$$("[data-om-page]")).toEqual([root]);
    expect(page.$$("[data-filter]").map((element) => element.textContent)).toEqual(["Active", "Archived"]);
    expect(() => page.$("[data-missing]")).toThrow("Element not found: [data-missing]");
  });

  it("listens to direct targets and emits page custom events with cleanup", async () => {
    document.body.innerHTML = `<main data-om-page="event-page"></main>`;
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    const ready = vi.fn();
    root.addEventListener("om:event-page:ready", ready);

    const registry = new PageRegistry();
    registry.register(EventPage);

    const instance = (await registry.mount(document)) as EventPage;
    window.dispatchEvent(new Event("resize"));
    root.dispatchEvent(new CustomEvent("om:event-page:local", { bubbles: true, detail: { value: "local" } }));
    await registry.unmount();
    window.dispatchEvent(new Event("resize"));
    root.dispatchEvent(new CustomEvent("om:event-page:local", { bubbles: true, detail: { value: "late" } }));

    expect((ready.mock.calls[0]?.[0] as CustomEvent | undefined)?.detail).toEqual({ state: "mounting" });
    expect(instance.calls).toEqual(["resize", "local"]);
  });

  it("exposes transition helpers and removes active helper classes on cleanup", async () => {
    document.body.innerHTML = `
      <main data-om-page="transition-page">
        <section id="panel" hidden></section>
        <button id="toggle"></button>
      </main>
    `;

    const registry = new PageRegistry();
    registry.register(TransitionPage);

    const instance = (await registry.mount(document)) as TransitionPage;
    const panel = document.querySelector<HTMLElement>("#panel")!;
    const button = document.querySelector<HTMLElement>("#toggle")!;

    expect(instance.calls).toEqual(["shown", "hidden", "shown", "true"]);
    expect(panel.hidden).toBe(false);
    expect(panel.classList.contains("is-loading")).toBe(true);
    expect(button.classList.contains("is-active")).toBe(true);

    await registry.unmount();
    expect(panel.classList.contains("is-loading")).toBe(false);
  });

  it("exposes page-scoped asset helpers and cleans page assets on unmount", async () => {
    document.body.innerHTML = `<main data-om-page="asset-page"></main>`;

    const registry = new PageRegistry();
    registry.register(AssetPage);

    const instance = (await registry.mount(document)) as AssetPage;

    expect(instance.calls).toEqual(["report-css", "report-widget", "2", "false"]);
    expect(document.querySelector("#report-css")).toBeInstanceOf(HTMLLinkElement);
    expect(document.querySelector("#report-widget")).toBeInstanceOf(HTMLScriptElement);
    expect(document.querySelector("#preview-css")).toBeNull();
    expect(document.querySelector("#preview-widget")).toBeNull();

    await registry.unmount();
    expect(document.querySelector("#report-css")).toBeNull();
    expect(document.querySelector("#report-widget")).toBeNull();
    expect(instance.calls).toEqual([
      "report-css",
      "report-widget",
      "2",
      "false",
      "report-widget:removed",
      "report-css:removed"
    ]);
  });

  it("exposes page-scoped preferences for durable UI state", async () => {
    document.body.innerHTML = `<main data-om-page="preference-page"></main>`;

    const registry = new PageRegistry();
    registry.register(PreferencePage);

    const instance = (await registry.mount(document)) as PreferencePage;

    expect(instance.preferences.get("audit.pageSize")).toBe("50");

    instance.preferences.remove("audit.pageSize");
    await registry.unmount();
  });

  it("mounts page-scoped components through the component registry", async () => {
    NestedComponent.mounted = 0;
    NestedComponent.unmounted = 0;
    document.body.innerHTML = `
      <main data-om-page="test-page">
        <section data-om-component="nested"></section>
      </main>
    `;

    const registry = new PageRegistry();
    registry.register(TestPage);

    await registry.mount(document);

    expect(NestedComponent.mounted).toBe(1);

    await registry.unmount();
    expect(NestedComponent.unmounted).toBe(1);
  });

  it("falls back to the global component registry for page components", async () => {
    GlobalPageComponent.mounted = 0;
    GlobalPageComponent.unmounted = 0;
    globalComponentRegistry.register(GlobalPageComponent);
    document.body.innerHTML = `
      <main data-om-page="global-component-page">
        <section data-om-component="global-page-component"></section>
      </main>
    `;

    const registry = new PageRegistry();
    registry.register(GlobalComponentPage);

    await registry.mount(document);

    expect(GlobalPageComponent.mounted).toBe(1);

    await registry.unmount();
    expect(GlobalPageComponent.unmounted).toBe(1);
  });

  it("propagates component unmount failures from page unmount", async () => {
    FailingUnmountComponent.calls = [];
    document.body.innerHTML = `
      <main data-om-page="failing-component-page">
        <section id="broken" data-om-component="failing-unmount"></section>
      </main>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    const registry = new PageRegistry();
    registry.register(FailingComponentPage);

    await registry.mount(document);
    await expect(registry.unmount()).rejects.toThrow("component unmount failed: broken");

    expect(FailingUnmountComponent.calls).toEqual(["broken"]);
    expect(root.dataset.omPageState).toBe("failed");
  });

  it("attempts every mounted page component unmount when one component fails", async () => {
    FailingUnmountComponent.calls = [];
    SuccessfulUnmountComponent.calls = [];
    document.body.innerHTML = `
      <main data-om-page="failing-component-page">
        <section id="broken" data-om-component="failing-unmount"></section>
        <section id="still-runs" data-om-component="successful-unmount"></section>
      </main>
    `;

    const registry = new PageRegistry();
    registry.register(FailingComponentPage);

    await registry.mount(document);
    await expect(registry.unmount()).rejects.toThrow("component unmount failed: broken");

    expect(FailingUnmountComponent.calls).toEqual(["broken"]);
    expect(SuccessfulUnmountComponent.calls).toEqual(["still-runs"]);
  });

  it("tracks page state and dispatches state change events", async () => {
    document.body.innerHTML = `
      <main data-om-page="admin-audit"></main>
    `;
    const states: string[] = [];
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    root.addEventListener("om:page:state", (event) => {
      states.push((event as CustomEvent<{ state: string }>).detail.state);
    });

    const registry = new PageRegistry();
    registry.register(AuditPage);

    const instance = await registry.mount(document);
    expect(instance?.state).toBe("mounted");
    expect(root.dataset.omPageState).toBe("mounted");

    await registry.unmount();

    expect(instance?.state).toBe("unmounted");
    expect(root.dataset.omPageState).toBe("unmounted");
    expect(states).toEqual(["mounting", "mounted", "unmounting", "unmounted"]);
  });

  it("does not mount the same page root twice", async () => {
    document.body.innerHTML = `<main data-om-page="admin-audit"></main>`;
    const registry = new PageRegistry();
    registry.register(AuditPage);

    const first = await registry.mount(document);
    const second = await registry.mount(document);
    await registry.unmount();

    expect(second).toBe(first);
    expect((first as AuditPage).calls).toEqual(["beforeMount", "mount", "afterMount", "beforeUnmount", "unmount"]);
  });

  it("unmounts the current page before mounting a different root", async () => {
    document.body.innerHTML = `<main id="first" data-om-page="admin-audit"></main>`;
    const registry = new PageRegistry();
    registry.register(AuditPage);

    const first = await registry.mount(document);
    document.body.innerHTML = `<main id="second" data-om-page="admin-audit"></main>`;
    const second = await registry.mount(document);

    expect(second).toBeInstanceOf(AuditPage);
    expect(second).not.toBe(first);
    expect((first as AuditPage).calls).toEqual(["beforeMount", "mount", "afterMount", "beforeUnmount", "unmount"]);
    expect((second as AuditPage).calls).toEqual(["beforeMount", "mount", "afterMount"]);
  });

  it("registers class pages with explicit names", async () => {
    class ExplicitNamePage extends Page {
      async mount() {
        this.root.dataset.mounted = "true";
      }
    }

    document.body.innerHTML = `<main data-om-page="explicit"></main>`;
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    const registry = new PageRegistry();
    registry.register("explicit", ExplicitNamePage);

    const instance = await registry.mount(document);

    expect(instance).toBeInstanceOf(ExplicitNamePage);
    expect(root.dataset.mounted).toBe("true");
  });

  it("marks a page as failed when mounting throws", async () => {
    class BrokenPage extends Page {
      static pageName = "broken";

      async mount() {
        throw new Error("broken");
      }
    }

    document.body.innerHTML = `<main data-om-page="broken"></main>`;
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    const registry = new PageRegistry();
    registry.register(BrokenPage);

    await expect(registry.mount(document)).rejects.toThrow("broken");
    expect(root.dataset.omPageState).toBe("failed");
  });

  it("unmounts page components before page cleanup when mount throws after component mount", async () => {
    const calls: string[] = [];

    class MountedThenBrokenComponent extends Component {
      static componentName = "mounted-then-broken";

      async mount() {
        calls.push("component mount");
      }

      async unmount() {
        calls.push("component unmount");
      }
    }

    class BrokenAfterComponentMountPage extends Page {
      static pageName = "broken-after-component-mount";

      async mount() {
        this.signal.addEventListener("abort", () => {
          calls.push("abort");
        });
        this.cleanup(() => {
          calls.push("page cleanup");
        });
        this.components.register(MountedThenBrokenComponent);
        await this.components.mount(this.root);
        throw new Error("mount failed");
      }
    }

    document.body.innerHTML = `
      <main data-om-page="broken-after-component-mount">
        <section data-om-component="mounted-then-broken"></section>
      </main>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    const registry = new PageRegistry();
    registry.register(BrokenAfterComponentMountPage);

    await expect(registry.mount(document)).rejects.toThrow("mount failed");

    expect(calls).toEqual(["component mount", "abort", "component unmount", "page cleanup"]);
    expect(root.dataset.omPageState).toBe("failed");
  });

  it("unmounts page components before page cleanup when afterMount throws", async () => {
    const calls: string[] = [];

    class MountedThenAfterMountBrokenComponent extends Component {
      static componentName = "mounted-then-after-mount-broken";

      async mount() {
        calls.push("component mount");
      }

      async unmount() {
        calls.push("component unmount");
      }
    }

    class BrokenAfterMountPage extends Page {
      static pageName = "broken-after-mount";

      async mount() {
        this.signal.addEventListener("abort", () => {
          calls.push("abort");
        });
        this.cleanup(() => {
          calls.push("page cleanup");
        });
        this.components.register(MountedThenAfterMountBrokenComponent);
        await this.components.mount(this.root);
      }

      async afterMount() {
        calls.push("afterMount");
        throw new Error("afterMount failed");
      }
    }

    document.body.innerHTML = `
      <main data-om-page="broken-after-mount">
        <section data-om-component="mounted-then-after-mount-broken"></section>
      </main>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    const registry = new PageRegistry();
    registry.register(BrokenAfterMountPage);

    await expect(registry.mount(document)).rejects.toThrow("afterMount failed");

    expect(calls).toEqual(["component mount", "afterMount", "abort", "component unmount", "page cleanup"]);
    expect(root.dataset.omPageState).toBe("failed");
  });

  it("aggregates component unmount failures with the original page mount failure", async () => {
    const calls: string[] = [];

    class BrokenUnmountAfterMountComponent extends Component {
      static componentName = "broken-unmount-after-mount";

      async mount() {
        calls.push("component mount");
      }

      async unmount() {
        calls.push("component unmount");
        throw new Error("component cleanup failed");
      }
    }

    class BrokenMountWithBrokenComponentCleanupPage extends Page {
      static pageName = "broken-mount-with-broken-component-cleanup";

      async mount() {
        this.cleanup(() => {
          calls.push("page cleanup");
        });
        this.components.register(BrokenUnmountAfterMountComponent);
        await this.components.mount(this.root);
        throw new Error("mount failed");
      }
    }

    document.body.innerHTML = `
      <main data-om-page="broken-mount-with-broken-component-cleanup">
        <section data-om-component="broken-unmount-after-mount"></section>
      </main>
    `;
    const registry = new PageRegistry();
    registry.register(BrokenMountWithBrokenComponentCleanupPage);

    await expect(registry.mount(document)).rejects.toMatchObject({
      message: "Page mount failed",
      errors: [expect.objectContaining({ message: "mount failed" }), expect.any(Error)]
    });

    expect(calls).toEqual(["component mount", "component unmount", "page cleanup"]);
  });

  it("runs page cleanup when beforeUnmount fails", async () => {
    const calls: string[] = [];

    class BrokenBeforeUnmountPage extends Page {
      static pageName = "broken-before-unmount";

      async mount() {
        this.cleanup(() => {
          calls.push("cleanup");
        });
      }

      async beforeUnmount() {
        calls.push("beforeUnmount");
        throw new Error("beforeUnmount failed");
      }

      async unmount() {
        calls.push("unmount");
      }
    }

    document.body.innerHTML = `<main data-om-page="broken-before-unmount"></main>`;
    const root = document.querySelector<HTMLElement>("[data-om-page]")!;
    const registry = new PageRegistry();
    registry.register(BrokenBeforeUnmountPage);

    await registry.mount(document);
    await expect(registry.unmount()).rejects.toThrow("beforeUnmount failed");

    expect(calls).toEqual(["beforeUnmount", "unmount", "cleanup"]);
    expect(root.dataset.omPageState).toBe("failed");
  });

  it("throws when a page entry is missing", async () => {
    document.body.innerHTML = `<main data-om-page="missing"></main>`;
    const registry = new PageRegistry();

    await expect(registry.mount(document)).rejects.toThrow("No page registered for missing");
  });
});
