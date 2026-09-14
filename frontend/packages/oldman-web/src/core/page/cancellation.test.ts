import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BasePage } from "../../app/index";
import { Component } from "../component/component";
import { ComponentManager } from "../component/manager";
import { createOldmanContext, resetOldmanContext, setOldmanContext } from "../runtime/context";
import { startOldman } from "../runtime/start";
import { Page } from "./page";
import { PageRegistry } from "./registry";
import { startPageLifecycle } from "./lifecycle";

/** Hold real lifecycle hooks without timers or a fake Page implementation. */
function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

let registry: PageRegistry;
class NextPage extends Page {}

beforeEach(() => {
  registry = new PageRegistry();
  setOldmanContext(createOldmanContext({ pageRegistry: registry }));
  document.body.innerHTML = '<main data-om-page="old"></main>';
  registry.register("next", NextPage);
});

afterEach(async () => {
  await registry.unmount();
  resetOldmanContext();
  vi.restoreAllMocks();
});

it.each(["success", "failure"])("discards late old Page %s without stopping the next Page", async (outcome) => {
  const pending = deferred();
  const lateHook = vi.fn();
  class OldPage extends Page {
    override async mount() { await pending.promise; }
    override async afterMount() { lateHook(); }
  }
  registry.register("old", OldPage);
  const initial = registry.mount();
  await vi.waitFor(() => expect(registry.current?.state).toBe("mounting"));
  const old = registry.current!;
  await registry.unmount();
  // Cancellation resolves the old mount before its external work has finished.
  expect(await initial).toBeNull();
  document.body.innerHTML = '<main data-om-page="next"></main>';
  const next = await registry.mount();
  if (outcome === "success") pending.resolve();
  else pending.reject(new Error("late failure"));
  await Promise.resolve();
  expect(lateHook).not.toHaveBeenCalled();
  expect(old.state).toBe("unmounted");
  expect(next?.state).toBe("mounted");
  expect(next?.signal.aborted).toBe(false);
  expect(registry.current).toBe(next);
});

it("cancels a Page module import before any Page instance exists", async () => {
  const pending = deferred();
  const loadPage = vi.fn(async () => { await pending.promise; registry.register("old", NextPage); });
  const initial = registry.mount(document, { loadPage });
  await vi.waitFor(() => expect(loadPage).toHaveBeenCalledOnce());
  expect(registry.current).toBeNull();
  await registry.unmount();
  expect(await initial).toBeNull();
  document.body.innerHTML = '<main data-om-page="next"></main>';
  const next = await registry.mount();
  pending.resolve();
  await Promise.resolve();
  expect(registry.current).toBe(next);
  expect(next?.signal.aborted).toBe(false);
});

it("keeps runtime listeners and context when the initial Page is cancelled", async () => {
  const pending = deferred();
  class OldPage extends Page { override async mount() { await pending.promise; } }
  registry.register("old", OldPage);
  const context = createOldmanContext({ pageRegistry: registry });
  const starting = startOldman({ context, turbo: false });
  await vi.waitFor(() => expect(registry.current?.state).toBe("mounting"));
  document.dispatchEvent(new CustomEvent("turbo:before-render"));
  document.body.innerHTML = '<main data-om-page="next"></main>';
  document.dispatchEvent(new CustomEvent("turbo:load"));
  const app = await starting;
  try {
    await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
    pending.reject(new Error("late import failed"));
    await Promise.resolve();
    expect(app.started).toBe(true);
    expect(registry.current).toBeInstanceOf(NextPage);
  } finally { await app.destroy(); }
});

it("aborts immediately but waits for cleanup before a document render resumes", async () => {
  const cleanup = deferred();
  class OldPage extends Page { override async beforeUnmount() { await cleanup.promise; } }
  registry.register("old", OldPage);
  const stop = await startPageLifecycle({ registry });
  const old = registry.current!;
  const resume = vi.fn();
  const event = new CustomEvent("turbo:before-render", { cancelable: true, detail: { resume } });
  document.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(old.signal.aborted).toBe(true);
  expect(resume).not.toHaveBeenCalled();
  cleanup.resolve();
  await vi.waitFor(() => expect(resume).toHaveBeenCalledOnce());
  await stop();
});

it("does not let a late component start unregister a replacement on the same root", async () => {
  const pending = deferred();
  const after = vi.fn();
  class Slow extends Component {
    override async mount() { await pending.promise; }
    override async afterMount() { after(); }
  }
  const manager = new ComponentManager();
  manager.register("probe", Slow);
  const root = document.querySelector("main")!;
  root.dataset.omComponent = "probe";
  const mounting = manager.mount(root).catch((error: unknown) => error);
  await vi.waitFor(() => expect(manager.get(root)?.state).toBe("mounting"));
  const old = manager.get(root)!;
  const stopping = manager.unmount(root);
  manager.register("probe", class extends Component {});
  const [next] = await manager.mount(root);
  await stopping;
  expect(await mounting).toMatchObject({ name: "AbortError" });
  pending.resolve();
  await Promise.resolve();
  expect(after).not.toHaveBeenCalled();
  expect(old.state).toBe("unmounted");
  expect(manager.get(root)).toBe(next);
  expect(next?.signal.aborted).toBe(false);
  await manager.unmount(root);
});

it("cancels initial private component loading before replacing a shared body root", async () => {
  const pending = deferred();
  const loader = vi.fn(async () => { await pending.promise; return class extends Component {}; });
  class OldPage extends BasePage {
    constructor(root: HTMLElement) { super({ root, componentLoaders: { probe: loader } }); }
  }
  registry.register("old", OldPage);
  document.body.innerHTML = '<main data-om-page="old"><turbo-frame id="oldman-main" data-om-page="old" data-turbo-action="advance"><div data-om-component="probe"></div></turbo-frame></main>';
  const starting = startPageLifecycle({ registry });
  await vi.waitFor(() => expect(loader).toHaveBeenCalledOnce());
  const old = registry.current!;
  const frame = document.querySelector("turbo-frame")!;
  const newFrame = document.createElement("turbo-frame");
  newFrame.dataset.omPage = "next";
  const resumed = deferred();
  frame.dispatchEvent(new CustomEvent("turbo:before-frame-render", {
    bubbles: true, cancelable: true, detail: { newFrame, resume: resumed.resolve }
  }));
  await resumed.promise;
  frame.replaceChildren();
  frame.dispatchEvent(new CustomEvent("turbo:frame-render", { bubbles: true }));
  const stop = await starting;
  try {
    await vi.waitFor(() => expect(registry.current?.state).toBe("mounted"));
    pending.resolve();
    await Promise.resolve();
    expect(registry.current).toBeInstanceOf(NextPage);
    expect(registry.current?.signal.aborted).toBe(false);
    expect(old.state).toBe("unmounted");
  } finally { await stop(); }
});
