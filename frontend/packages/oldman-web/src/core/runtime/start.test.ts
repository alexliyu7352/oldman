import { afterEach, describe, expect, it, vi } from "vitest";
import { Application, Controller } from "@hotwired/stimulus";
import { Page } from "../page/page";
import { registerPage } from "../page/registry";
import { createOldmanContext, getOldmanContext, resetOldmanContext } from "./context";
import { startOldman } from "./start";
import { clearPendingControllers, getStimulusApplication, registerController } from "../stimulus/controllers";
import type { HttpClient } from "../http/client";

const runtimeCalls: string[] = [];

class RuntimePage extends Page {
  static pageName = "runtime";
  mounted = false;

  async mount() {
    this.mounted = true;
    runtimeCalls.push(`mount:${this.root.id}`);
  }

  async unmount() {
    runtimeCalls.push(`unmount:${this.root.id}`);
  }
}

class FailingUnmountRuntimePage extends Page {
  static pageName = "failing-unmount-runtime";

  async unmount() {
    throw new Error("runtime unmount failed");
  }
}

/**
 * 导航期间由 runtime pageLoader 注册的页面夹具。
 */
class LazyRuntimePage extends Page {
  static pageName = "lazy-runtime";

  /**
   * 记录懒加载页面已经被生命周期队列挂载。
   */
  async mount() {
    runtimeCalls.push(`lazy-mount:${this.root.id}`);
  }
}

class ContextRuntimePage extends Page {
  static pageName = "context-runtime";
  static http: HttpClient | null = null;

  async mount() {
    ContextRuntimePage.http = this.http;
  }
}

const stimulusCalls: string[] = [];

class RuntimeController extends Controller {
  connect() {
    stimulusCalls.push(`connect:${this.element.id}`);
  }
}

describe("startOldman", () => {
  afterEach(() => {
    clearPendingControllers();
    resetOldmanContext();
    ContextRuntimePage.http = null;
    vi.restoreAllMocks();
  });

  it("mounts pages on start and unmounts on destroy", async () => {
    document.body.innerHTML = `<main data-om-page="runtime"></main>`;
    registerPage(RuntimePage);

    const app = await startOldman({ turbo: false, actions: false });
    expect(app.started).toBe(true);

    await app.destroy();
    expect(app.started).toBe(false);
  });

  it("destroys the runtime once when destroy is called multiple times", async () => {
    document.body.innerHTML = `<main data-om-page="runtime"></main>`;
    registerPage(RuntimePage);

    const app = await startOldman({ turbo: false, actions: false });
    const stop = vi.spyOn(app.application, "stop");

    await Promise.all([app.destroy(), app.destroy()]);
    await app.destroy();

    expect(stop).toHaveBeenCalledOnce();
    expect(app.started).toBe(false);
  });

  it("always disables Turbo hover prefetch", async () => {
    document.body.innerHTML = `<main data-om-page="runtime"></main>`;
    registerPage(RuntimePage);
    const Turbo = await import("@hotwired/turbo");

    Turbo.session.linkPrefetchObserver.start();
    expect(Turbo.session.linkPrefetchObserver.started).toBe(true);

    const app = await startOldman({ actions: false });

    expect(Turbo.session.linkPrefetchObserver.started).toBe(false);
    await app.destroy();
  });

  it("unmounts and remounts pages across turbo navigation events", async () => {
    runtimeCalls.length = 0;
    document.body.innerHTML = `<main id="first" data-om-page="runtime"></main>`;
    registerPage(RuntimePage);

    const app = await startOldman({ turbo: false, actions: false });

    document.dispatchEvent(new CustomEvent("turbo:before-render"));
    await vi.waitFor(() => {
      expect(runtimeCalls).toContain("unmount:first");
    });

    document.body.innerHTML = `<main id="second" data-om-page="runtime"></main>`;
    document.dispatchEvent(new CustomEvent("turbo:load"));
    await vi.waitFor(() => {
      expect(runtimeCalls).toContain("mount:second");
    });

    await app.destroy();

    expect(runtimeCalls).toEqual(["mount:first", "unmount:first", "mount:second", "unmount:second"]);
  });

  it("loads unregistered page entries before mounting turbo-rendered pages", async () => {
    runtimeCalls.length = 0;
    document.body.innerHTML = `<main id="first" data-om-page="runtime"></main>`;
    registerPage(RuntimePage);
    /**
     * 模拟 Vite 动态 import，并注册请求的页面入口。
     */
    const pageLoader = vi.fn(async (pageName: string) => {
      if (pageName === "lazy-runtime") registerPage(LazyRuntimePage);
    });

    const app = await startOldman({ turbo: false, actions: false, pageLoader });

    document.dispatchEvent(new CustomEvent("turbo:before-render"));
    await vi.waitFor(() => {
      expect(runtimeCalls).toContain("unmount:first");
    });

    document.body.innerHTML = `<main id="lazy" data-om-page="lazy-runtime"></main>`;
    document.dispatchEvent(new CustomEvent("turbo:load"));
    await vi.waitFor(() => {
      expect(runtimeCalls).toContain("lazy-mount:lazy");
    });

    await app.destroy();

    expect(pageLoader).toHaveBeenCalledWith("lazy-runtime", document.querySelector("#lazy"));
    expect(runtimeCalls).toEqual(["mount:first", "unmount:first", "lazy-mount:lazy"]);
  });

  it("registers startup stimulus controllers and clears the current application on destroy", async () => {
    stimulusCalls.length = 0;
    document.body.innerHTML = `<div id="widget" data-controller="runtime"></div>`;

    const app = await startOldman({
      turbo: false,
      actions: false,
      controllers: {
        runtime: RuntimeController
      }
    });

    expect(getStimulusApplication()).toBe(app.application);
    await vi.waitFor(() => {
      expect(stimulusCalls).toEqual(["connect:widget"]);
    });

    await app.destroy();
    expect(getStimulusApplication()).toBeNull();
  });

  it("stops and resets stimulus when page lifecycle stop fails during destroy", async () => {
    document.body.innerHTML = `<main data-om-page="failing-unmount-runtime"></main>`;
    registerPage(FailingUnmountRuntimePage);

    const app = await startOldman({ turbo: false, actions: false });
    const stop = vi.spyOn(app.application, "stop");

    await expect(app.destroy()).rejects.toThrow("runtime unmount failed");

    expect(stop).toHaveBeenCalledOnce();
    expect(getStimulusApplication()).toBeNull();
    expect(app.started).toBe(false);
  });

  it("stops and resets stimulus when controller registration fails during startup", async () => {
    const application = {
      register: vi.fn(() => {
        throw new Error("controller registration failed");
      }),
      stop: vi.fn()
    } as unknown as Application;
    vi.spyOn(Application, "start").mockReturnValue(application);

    await expect(
      startOldman({
        turbo: false,
        actions: false,
        controllers: {
          runtime: RuntimeController
        }
      })
    ).rejects.toThrow("controller registration failed");

    expect(application.stop).toHaveBeenCalledOnce();
    expect(getStimulusApplication()).toBeNull();
  });

  it("does not poison later startup attempts when queued controller registration fails", async () => {
    document.body.innerHTML = "";
    const application = {
      register: vi.fn(() => {
        throw new Error("queued controller registration failed");
      }),
      stop: vi.fn()
    } as unknown as Application;
    vi.spyOn(Application, "start").mockReturnValueOnce(application);

    registerController("queued", RuntimeController);

    await expect(startOldman({ turbo: false, actions: false })).rejects.toThrow(
      "queued controller registration failed"
    );

    expect(application.stop).toHaveBeenCalledOnce();
    expect(getStimulusApplication()).toBeNull();

    const app = await startOldman({ turbo: false, actions: false });
    try {
      const router = app.application.router as unknown as { modulesByIdentifier: Map<string, unknown> };
      expect(router.modulesByIdentifier.has("queued")).toBe(false);

      const register = vi.spyOn(app.application, "register");
      registerController("late", RuntimeController);

      expect(register).toHaveBeenCalledOnce();
      expect(register).toHaveBeenCalledWith("late", RuntimeController);
    } finally {
      await app.destroy();
    }
  });

  it("registers controllers against the active stimulus application", async () => {
    stimulusCalls.length = 0;
    document.body.innerHTML = `<div id="late-widget" data-controller="late"></div>`;

    const app = await startOldman({ turbo: false, actions: false });
    registerController("late", RuntimeController);

    await vi.waitFor(() => {
      expect(stimulusCalls).toEqual(["connect:late-widget"]);
    });

    await app.destroy();
  });

  it("registers page-entry controllers queued before the runtime starts", async () => {
    stimulusCalls.length = 0;
    document.body.innerHTML = `<div id="early-widget" data-controller="early"></div>`;

    registerController("early", RuntimeController);
    const app = await startOldman({ turbo: false, actions: false });

    await vi.waitFor(() => {
      expect(stimulusCalls).toEqual(["connect:early-widget"]);
    });

    await app.destroy();
  });

  it("uses an injected http client for runtime actions and forwards action options", async () => {
    document.body.innerHTML = `
      <main data-om-page="runtime">
        <button
          data-om-action="post"
          data-om-confirm="Save?"
          data-om-url="/users"
          data-om-target="#row"
        >
          Save
        </button>
        <div id="row">old</div>
      </main>
    `;
    registerPage(RuntimePage);

    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return {
        error_code: 0,
        message: "",
        data: {},
        actions: [{ action: "replace_html", html: "<span>saved</span>" }]
      } as T;
    };
    const http: HttpClient = {
      axios: {} as HttpClient["axios"],
      getJson: vi.fn(),
      html: vi.fn(),
      postForm: vi.fn(),
      postJson: vi.fn(),
      requestJson
    };
    const confirm = vi.fn(() => true);

    const app = await startOldman({
      turbo: false,
      httpClient: http,
      actions: {
        confirm,
        validate: false
      }
    });

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => {
      expect(document.querySelector("#row")!.innerHTML).toBe("<span>saved</span>");
    });

    expect(app.http).toBe(http);
    expect(confirm).toHaveBeenCalledWith("Save?");
    expect(requestJsonCalls).toEqual([["post", "/users", {}, expect.any(Object)]]);

    await app.destroy();
  });

  it("installs a runtime context that mounted pages use", async () => {
    document.body.innerHTML = `<main data-om-page="context-runtime"></main>`;
    registerPage(ContextRuntimePage);
    const http: HttpClient = {
      axios: {} as HttpClient["axios"],
      getJson: vi.fn(),
      html: vi.fn(),
      postForm: vi.fn(),
      postJson: vi.fn(),
      requestJson: vi.fn()
    };
    const scopedHttp = {
      ...http,
      axios: {} as HttpClient["axios"]
    };
    const httpFactory = vi.fn(() => scopedHttp);
    const context = createOldmanContext({ http, httpFactory });

    const app = await startOldman({ turbo: false, actions: false, context });

    expect(app.http).toBe(http);
    expect(getOldmanContext().http).toBe(http);
    expect(ContextRuntimePage.http).toBe(scopedHttp);
    expect(httpFactory).toHaveBeenCalledWith({ signal: expect.any(AbortSignal), onAuthRedirect: expect.any(Function) });

    await app.destroy();
  });

  it("uses the provided httpClient for mounted pages when no scoped factory is configured", async () => {
    document.body.innerHTML = `<main data-om-page="context-runtime"></main>`;
    registerPage(ContextRuntimePage);
    const http: HttpClient = {
      axios: {} as HttpClient["axios"],
      getJson: vi.fn(),
      html: vi.fn(),
      postForm: vi.fn(),
      postJson: vi.fn(),
      requestJson: vi.fn()
    };

    const app = await startOldman({ turbo: false, actions: false, httpClient: http });

    expect(app.http).toBe(http);
    expect(getOldmanContext().http).toBe(http);
    expect(ContextRuntimePage.http).toBe(http);

    await app.destroy();
  });

  it("cleans up partial runtime state when startup fails", async () => {
    document.body.innerHTML = `
      <button data-om-action="post" data-om-url="/users">Save</button>
      <main data-om-page="missing"></main>
    `;
    const requestJsonCalls: unknown[][] = [];
    const requestJson = async <T>(...args: Parameters<NonNullable<HttpClient["requestJson"]>>) => {
      requestJsonCalls.push(args);
      return { html: "" } as T;
    };
    const http: HttpClient = {
      axios: {} as HttpClient["axios"],
      getJson: vi.fn(),
      html: vi.fn(),
      postForm: vi.fn(),
      postJson: vi.fn(),
      requestJson
    };
    const stop = vi.spyOn(Application.prototype, "stop");

    await expect(startOldman({ turbo: false, httpClient: http })).rejects.toThrow("No page registered for missing");

    expect(stop).toHaveBeenCalledOnce();
    expect(getStimulusApplication()).toBeNull();

    document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    await Promise.resolve();

    expect(requestJsonCalls).toEqual([]);
  });

  it("starts with the fallback page when the entry name is unknown", async () => {
    document.body.innerHTML = `<main data-om-page="missing"></main>`;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    class FallbackPage extends Page {
      override async mount(): Promise<void> {
        this.root.dataset.fallbackMounted = "true";
      }
    }

    const app = await startOldman({ turbo: false, fallbackPage: FallbackPage });
    try {
      expect(document.querySelector<HTMLElement>("main")!.dataset.fallbackMounted).toBe("true");
      expect(warn).toHaveBeenCalledWith("No page registered for missing; falling back to FallbackPage");
    } finally {
      await app.destroy();
      warn.mockRestore();
    }
  });

  it("preserves startup errors when partial runtime cleanup fails", async () => {
    document.body.innerHTML = `<main data-om-page="missing"></main>`;
    const actionRoot = document.createElement("div");
    vi.spyOn(actionRoot, "removeEventListener").mockImplementation(() => {
      throw new Error("cleanup failed");
    });
    const stop = vi.spyOn(Application.prototype, "stop");

    await expect(
      startOldman({
        turbo: false,
        actions: {
          root: actionRoot
        }
      })
    ).rejects.toThrow("No page registered for missing");

    expect(stop).toHaveBeenCalledOnce();
    expect(getStimulusApplication()).toBeNull();
  });
});
