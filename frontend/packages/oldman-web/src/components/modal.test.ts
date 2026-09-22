import { afterEach, describe, expect, it, vi } from "vitest";
import { Page } from "../core/page/page";
import { Modal } from "./modal";

class ModalTestPage extends Page {}

describe("Modal", () => {
  // 失败的用例不会走到自己末尾的 restore，mock 会漏给下一个用例（含对照组）。
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens and closes the modal root", async () => {
    document.body.innerHTML = `<section class="hidden" hidden></section>`;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);

    await modal.start();
    await modal.open();

    expect(root.hidden).toBe(false);
    expect(root.classList.contains("hidden")).toBe(false);
    expect(root.dataset.omState).toBe("open");

    modal.close("programmatic");

    expect(root.hidden).toBe(true);
    expect(root.dataset.omState).toBe("closed");
  });

  it("emits modal lifecycle events and closes from user gestures", async () => {
    document.body.innerHTML = `
      <section hidden>
        <article data-om-modal-content>
          <button data-om-modal-close>Close</button>
        </article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);
    const opened = vi.fn();
    const closed = vi.fn();
    root.addEventListener("om:modal:open", opened);
    root.addEventListener("om:modal:close", closed);

    await modal.start();
    modal.open();
    document.querySelector<HTMLButtonElement>("[data-om-modal-close]")!.click();

    expect(opened).toHaveBeenCalledTimes(1);
    expect(closed).toHaveBeenLastCalledWith(expect.objectContaining({ detail: { component: modal, reason: "dismiss" } }));
    expect(root.hidden).toBe(true);

    modal.open();
    root.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(root.dataset.omState).toBe("closed");
    expect(closed).toHaveBeenLastCalledWith(expect.objectContaining({ detail: { component: modal, reason: "outside" } }));

    modal.open();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

    expect(root.dataset.omState).toBe("closed");
    expect(closed).toHaveBeenLastCalledWith(expect.objectContaining({ detail: { component: modal, reason: "escape" } }));
  });

  it("honors close behavior configuration", async () => {
    document.body.innerHTML = `
      <section hidden>
        <article data-om-modal-content></article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root, { closeOnEscape: false, closeOnOutside: false });

    await modal.start();
    modal.open();
    root.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

    expect(root.dataset.omState).toBe("open");
    expect(root.hidden).toBe(false);

    modal.close("programmatic");
  });

  it("lets Escape close only the topmost nested modal", async () => {
    document.body.innerHTML = `
      <section id="outer" hidden><article data-om-modal-content></article></section>
      <section id="inner" hidden><article data-om-modal-content></article></section>
    `;
    const outerRoot = document.querySelector<HTMLElement>("#outer")!;
    const innerRoot = document.querySelector<HTMLElement>("#inner")!;
    const outer = new Modal(outerRoot);
    const inner = new Modal(innerRoot);
    await outer.start();
    await inner.start();
    outer.open();
    inner.open();

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(innerRoot.hidden).toBe(true);
    expect(outerRoot.hidden).toBe(false);

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(outerRoot.hidden).toBe(true);
    await inner.stop();
    await outer.stop();
  });

  it("uses surfaceSelector for outside click detection separately from contentSelector", async () => {
    document.body.innerHTML = `
      <section hidden>
        <article class="custom-modal-surface">
          <header><button id="header-action">Header</button></header>
          <div class="om-modal-surface">
            <div class="custom-modal-body"></div>
          </div>
        </article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root, {
      contentSelector: ".custom-modal-body",
      surfaceSelector: ".custom-modal-surface"
    });

    await modal.start();
    modal.open();
    document.querySelector<HTMLButtonElement>("#header-action")!.click();

    expect(root.dataset.omState).toBe("open");
    expect(root.hidden).toBe(false);

    root.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(root.dataset.omState).toBe("closed");
  });

  it("prioritizes an explicitly configured contentSelector over the default content marker", async () => {
    document.body.innerHTML = `
      <section hidden>
        <article data-om-modal-content>Default content</article>
        <article class="custom-modal-body">Custom content</article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root, { contentSelector: ".custom-modal-body" });

    await modal.start();
    modal.setContent("<p>Updated</p>");

    expect(root.querySelector<HTMLElement>(".custom-modal-body")?.innerHTML).toBe("<p>Updated</p>");
    expect(root.querySelector<HTMLElement>("[data-om-modal-content]")?.textContent).toBe("Default content");
  });

  it("sets local and remote modal content with loading and success states", async () => {
    document.body.innerHTML = `
      <section hidden>
        <article data-om-modal-content></article>
        <p data-om-modal-status hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);
    const contentLoaded = vi.fn();
    root.addEventListener("om:modal:content", contentLoaded);
    Object.assign(modal.http, { html: vi.fn().mockResolvedValue("<form>Loaded</form>") });

    await modal.start();
    modal.setContent("<p>Local</p>");
    expect(root.querySelector("[data-om-modal-content]")?.innerHTML).toBe("<p>Local</p>");

    await modal.loadContent("/users/1/edit");

    expect(modal.http.html).toHaveBeenCalledWith("/users/1/edit");
    expect(root.querySelector("[data-om-modal-content]")?.innerHTML).toBe("<form>Loaded</form>");
    expect(root.dataset.omStatus).toBe("success");
    expect(root.querySelector<HTMLElement>("[data-om-modal-status]")?.hidden).toBe(true);
    expect(contentLoaded).toHaveBeenLastCalledWith(
      expect.objectContaining({ detail: { component: modal, html: "<form>Loaded</form>", url: "/users/1/edit" } })
    );
  });

  it("updates title, body, and footer fragments without replacing the whole modal", async () => {
    document.body.innerHTML = `
      <section hidden>
        <h2 data-om-modal-title></h2>
        <article data-om-modal-content></article>
        <footer data-om-modal-footer></footer>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);

    await modal.start();
    modal.setParts({
      title: "编辑用户",
      body: "<form><input name='name' value='Anna'></form>",
      footer: "<button type='submit'>保存</button>"
    });

    expect(root.querySelector<HTMLElement>("[data-om-modal-title]")?.textContent).toBe("编辑用户");
    expect(root.querySelector<HTMLElement>("[data-om-modal-content]")?.innerHTML).toContain("name=\"name\"");
    expect(root.querySelector<HTMLElement>("[data-om-modal-footer]")?.innerHTML).toContain("保存");
    expect(root.querySelector<HTMLElement>("[data-om-modal-footer]")?.hidden).toBe(false);
  });

  it("renders modal title HTML while keeping body and footer HTML fragments", async () => {
    document.body.innerHTML = `
      <section hidden>
        <h2 data-om-modal-title></h2>
        <article data-om-modal-content></article>
        <footer data-om-modal-footer></footer>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);

    await modal.start();
    modal.setParts({
      title: '<i class="ri-user-settings-line"></i> 编辑用户 · Alice &amp; Admin',
      body: "<form><input name='name' value='Anna'></form>",
      footer: "<button type='submit'>保存</button>"
    });

    const title = root.querySelector<HTMLElement>("[data-om-modal-title]")!;
    expect(title.querySelector(".ri-user-settings-line")).not.toBeNull();
    expect(title.textContent).toBe(" 编辑用户 · Alice & Admin");
    expect(root.querySelector<HTMLElement>("[data-om-modal-content]")?.innerHTML).toContain("name=\"name\"");
    expect(root.querySelector<HTMLElement>("[data-om-modal-footer]")?.innerHTML).toContain("保存");
  });

  it("loads remote JSON fragments into title, body, and footer", async () => {
    document.body.innerHTML = `
      <section hidden>
        <h2 data-om-modal-title></h2>
        <article data-om-modal-content></article>
        <footer data-om-modal-footer></footer>
        <p data-om-modal-status hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);
    Object.assign(modal.http, {
      getJson: vi.fn().mockResolvedValue({
        title: "编辑用户",
        html: "<form><input name='name' value='Anna'></form>",
        footer: "<button type='submit'>保存</button>"
      })
    });

    await modal.start();
    await modal.loadParts("/users/anna/edit");

    expect(modal.http.getJson).toHaveBeenCalledWith("/users/anna/edit");
    expect(root.querySelector<HTMLElement>("[data-om-modal-title]")?.textContent).toBe("编辑用户");
    expect(root.querySelector<HTMLElement>("[data-om-modal-content]")?.innerHTML).toContain("name=\"name\"");
    expect(root.querySelector<HTMLElement>("[data-om-modal-footer]")?.innerHTML).toContain("保存");
    expect(root.dataset.omStatus).toBe("success");
  });

  it("focuses modal content on open and restores the previous focus on close", async () => {
    document.body.innerHTML = `
      <button id="opener">打开</button>
      <section hidden>
        <article data-om-modal-content tabindex="-1">
          <button id="primary-action">保存</button>
        </article>
      </section>
    `;
    const opener = document.querySelector<HTMLButtonElement>("#opener")!;
    const primaryAction = document.querySelector<HTMLButtonElement>("#primary-action")!;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);

    await modal.start();
    opener.focus();
    modal.open();

    expect(document.activeElement).toBe(primaryAction);

    modal.close("programmatic");

    expect(document.activeElement).toBe(opener);
  });

  it("opens from a declarative trigger and loads remote fragments before showing", async () => {
    document.body.innerHTML = `
      <button id="edit-user" data-om-modal-target="#user-modal" data-om-modal-url="/users/anna/edit">编辑</button>
      <section id="user-modal" hidden>
        <h2 data-om-modal-title></h2>
        <article data-om-modal-content></article>
        <footer data-om-modal-footer></footer>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("#user-modal")!;
    const modal = new Modal(root);
    Object.assign(modal.http, {
      getJson: vi.fn().mockResolvedValue({
        title: "编辑 Anna",
        html: "<form><input name='name' value='Anna'></form>",
        footer: "<button type='submit'>保存</button>"
      })
    });

    await modal.start();
    document.querySelector<HTMLButtonElement>("#edit-user")!.click();
    await vi.waitFor(() => expect(root.hidden).toBe(false));

    expect(modal.http.getJson).toHaveBeenCalledWith("/users/anna/edit");
    expect(root.querySelector<HTMLElement>("[data-om-modal-title]")?.textContent).toBe("编辑 Anna");
    expect(root.querySelector<HTMLElement>("[data-om-modal-content]")?.innerHTML).toContain("name=\"name\"");
    expect(root.querySelector<HTMLElement>("[data-om-modal-footer]")?.innerHTML).toContain("保存");

    modal.close("programmatic");
    await modal.stop();
  });

  it("keeps the original focus target across repeated remote content loads", async () => {
    document.body.innerHTML = `
      <button id="opener" data-om-modal-target="#remote-modal" data-om-modal-url="/first">Open</button>
      <section id="remote-modal" hidden>
        <h2 data-om-modal-title></h2>
        <article data-om-modal-content></article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("#remote-modal")!;
    const opener = document.querySelector<HTMLButtonElement>("#opener")!;
    const modal = new Modal(root);
    Object.assign(modal.http, {
      getJson: vi.fn()
        .mockResolvedValueOnce({
          title: "First",
          html: '<button id="next" data-om-modal-target="#remote-modal" data-om-modal-url="/second">Next</button>'
        })
        .mockResolvedValueOnce({ title: "Second", html: "<p>Done</p>" })
    });

    await modal.start();
    opener.focus();
    opener.click();
    await vi.waitFor(() => expect(root.hidden).toBe(false));
    const next = document.querySelector<HTMLButtonElement>("#next")!;
    next.focus();
    next.click();
    await vi.waitFor(() => expect(root.textContent).toContain("Done"));
    modal.close("programmatic");

    expect(document.activeElement).toBe(opener);
    await modal.stop();
  });

  it("mounts declarative components added by remote parts", async () => {
    document.body.innerHTML = `
      <section>
        <h5 data-om-modal-title></h5>
        <article data-om-modal-content></article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const manager = {
      mount: vi.fn().mockResolvedValue([]),
      unmount: vi.fn(),
      unmountDescendants: vi.fn().mockResolvedValue(undefined),
      get: vi.fn()
    };
    const modal = new Modal(root, { manager: manager as never });
    Object.assign(modal.http, {
      getJson: vi.fn().mockResolvedValue({
        html: '<form data-om-component="form-validator" data-om-form></form>',
        title: "Edit"
      })
    });

    await modal.start();
    await modal.loadParts("/modal");

    expect(root.querySelector('[data-om-component="form-validator"]')).not.toBeNull();
    expect(manager.unmountDescendants).toHaveBeenCalledWith(root.querySelector("[data-om-modal-title]"));
    expect(manager.unmountDescendants).toHaveBeenCalledWith(root.querySelector("[data-om-modal-content]"));
    expect(manager.mount).toHaveBeenCalledWith(root);
    expect(manager.unmountDescendants.mock.invocationCallOrder.at(-1)).toBeLessThan(
      manager.mount.mock.invocationCallOrder[0]!
    );
  });

  it("声明式触发打开时会把触发元素传给打开事件", async () => {
    document.body.innerHTML = `
      <button id="edit-user" data-om-modal-target="#user-modal" data-user-id="42">编辑</button>
      <section id="user-modal" hidden>
        <article data-om-modal-content></article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("#user-modal")!;
    const trigger = document.querySelector<HTMLButtonElement>("#edit-user")!;
    const modal = new Modal(root);
    const opened = vi.fn();
    root.addEventListener("om:modal:open", opened);

    await modal.start();
    trigger.click();

    expect(opened).toHaveBeenCalledWith(expect.objectContaining({ detail: { component: modal, trigger } }));

    modal.close("programmatic");
    await modal.stop();
  });

  it("creates backdrop, locks body scroll, and updates aria state while open", async () => {
    document.body.innerHTML = `
      <section hidden>
        <article data-om-modal-content tabindex="-1"></article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);

    await modal.start();
    modal.open();

    expect(document.querySelector("[data-om-modal-backdrop]")).not.toBeNull();
    expect(document.body.classList.contains("om-modal-open")).toBe(true);
    expect(root.getAttribute("role")).toBe("dialog");
    expect(root.getAttribute("aria-modal")).toBe("true");
    expect(root.getAttribute("aria-hidden")).toBe("false");

    modal.close("programmatic");

    expect(document.querySelector("[data-om-modal-backdrop]")).toBeNull();
    expect(document.body.classList.contains("om-modal-open")).toBe(false);
    expect(root.getAttribute("aria-hidden")).toBe("true");
  });

  it("supports configured visual classes and delayed close transitions", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <section hidden style="display: none;">
        <article class="dialog" style="transition-duration: 0.3s;"></article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root, {
      backdropClass: "theme-backdrop entering",
      backdropOpenClass: "is-open",
      forceReflowOnOpen: true,
      hiddenDisplay: "none",
      openClass: "is-open",
      transitionElementSelector: ".dialog",
      visibleDisplay: "block"
    });

    await modal.start();
    modal.open();

    expect(root.style.display).toBe("block");
    expect(root.classList.contains("is-open")).toBe(true);
    expect(document.querySelector<HTMLElement>("[data-om-modal-backdrop]")?.className).toBe("theme-backdrop entering is-open");

    modal.close("programmatic");

    expect(root.hidden).toBe(false);
    expect(root.dataset.omState).toBe("closing");
    expect(root.style.display).toBe("block");
    expect(root.classList.contains("is-open")).toBe(false);
    expect(document.querySelector<HTMLElement>("[data-om-modal-backdrop]")?.className).toBe("theme-backdrop entering");

    document.querySelector<HTMLElement>(".dialog")!.dispatchEvent(new Event("transitionend"));
    expect(root.hidden).toBe(false);
    expect(root.dataset.omState).toBe("closing");

    vi.advanceTimersByTime(316);
    await Promise.resolve();

    expect(root.hidden).toBe(true);
    expect(root.style.display).toBe("none");
    expect(root.dataset.omState).toBe("closed");
    expect(document.querySelector("[data-om-modal-backdrop]")).toBeNull();

    vi.useRealTimers();
  });

  it("keeps tab focus inside the open modal", async () => {
    document.body.innerHTML = `
      <button id="outside">外部按钮</button>
      <section hidden>
        <article data-om-modal-content>
          <button id="first">第一个</button>
          <button id="last">最后一个</button>
        </article>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);

    await modal.start();
    modal.open();
    document.querySelector<HTMLButtonElement>("#last")!.focus();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));

    expect(document.activeElement).toBe(document.querySelector("#first"));

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, shiftKey: true }));

    expect(document.activeElement).toBe(document.querySelector("#last"));
  });

  it("records remote loading errors and rethrows them", async () => {
    document.body.innerHTML = `
      <section hidden>
        <article data-om-modal-content></article>
        <p data-om-modal-status hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);
    const error = new Error("加载失败");
    const failed = vi.fn();
    root.addEventListener("om:modal:error", failed);
    Object.assign(modal.http, { html: vi.fn().mockRejectedValue(error) });

    await modal.start();

    await expect(modal.loadContent("/broken")).rejects.toThrow("加载失败");
    expect(root.dataset.omStatus).toBe("error");
    expect(root.querySelector<HTMLElement>("[data-om-modal-status]")?.hidden).toBe(false);
    expect(root.querySelector<HTMLElement>("[data-om-modal-status]")?.textContent).toBe("加载失败");
    expect(failed).toHaveBeenLastCalledWith(
      expect.objectContaining({ detail: { component: modal, error, message: "加载失败", url: "/broken" } })
    );
  });

  it("keeps explicit remote-parts loading rejectable for API callers", async () => {
    document.body.innerHTML = `
      <section hidden>
        <article data-om-modal-content></article>
        <p data-om-modal-status hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);
    const error = new Error("Parts failed");
    Object.assign(modal.http, { getJson: vi.fn().mockRejectedValue(error) });

    await modal.start();

    await expect(modal.loadParts("/broken-parts")).rejects.toBe(error);
    expect(root.dataset.omStatus).toBe("error");
  });

  it("records declarative remote loading failures without opening stale modal content", async () => {
    document.body.innerHTML = `
      <button data-om-modal-target="#remote-modal" data-om-modal-url="/expired">Open</button>
      <section id="remote-modal" hidden>
        <article data-om-modal-content></article>
        <p data-om-modal-status hidden></p>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("#remote-modal")!;
    const modal = new Modal(root);
    const error = new Error("Authentication required");
    const failed = vi.fn();
    root.addEventListener("om:modal:error", failed);
    Object.assign(modal.http, { getJson: vi.fn().mockRejectedValue(error) });

    await modal.start();
    document.querySelector<HTMLButtonElement>("button")!.click();
    await vi.waitFor(() => expect(failed).toHaveBeenCalledOnce());

    expect(root.hidden).toBe(true);
    expect(root.classList.contains("is-open")).toBe(false);
    expect(root.dataset.omStatus).toBe("error");
    expect(root.querySelector<HTMLElement>("[data-om-modal-status]")?.hidden).toBe(false);
    expect(root.querySelector<HTMLElement>("[data-om-modal-status]")?.textContent).toBe("Authentication required");
    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({ detail: { component: modal, error, message: "Authentication required", url: "/expired" } })
    );
  });

  it("shows declarative failures once through Page Feedback but not after cancellation", async () => {
    document.body.innerHTML = `
      <button data-om-modal-target="#owned-remote-modal" data-om-modal-url="/broken">Open</button>
      <section id="owned-remote-modal" hidden><article data-om-modal-content>Old content</article></section>
    `;
    const root = document.querySelector<HTMLElement>("#owned-remote-modal")!;
    const page = new ModalTestPage(document.body);
    const alert = vi.fn().mockResolvedValue({});
    page.feedback = { alert, toast: vi.fn(), close: vi.fn() };
    const modal = new Modal(root, { page });
    const error = new Error("Service unavailable");
    const getJson = vi.fn().mockRejectedValue(error);
    Object.assign(modal.http, { getJson });
    await modal.start();
    try {
      document.querySelector<HTMLButtonElement>("button")!.click();
      await vi.waitFor(() => expect(alert).toHaveBeenCalledOnce());
      expect(alert).toHaveBeenCalledWith({ icon: "error", titleText: "Request failed" });
      expect(root.hidden).toBe(true);
      expect(root.textContent).toBe("Old content");

      // An explicit caller still owns its failure presentation.
      await expect(modal.loadParts("/broken")).rejects.toBe(error);
      expect(alert).toHaveBeenCalledOnce();

      let reject: (reason: unknown) => void = () => {};
      getJson.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
      document.querySelector<HTMLButtonElement>("button")!.click();
      await modal.stop();
      reject(error);
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(alert).toHaveBeenCalledOnce();
      expect(root.hidden).toBe(true);
    } finally {
      await modal.stop();
    }
  });

  it("emits destroy before stopping the component", async () => {
    document.body.innerHTML = `<section></section>`;
    const root = document.querySelector<HTMLElement>("section")!;
    const modal = new Modal(root);
    const destroyed = vi.fn();
    root.addEventListener("om:modal:destroy", destroyed);

    await modal.start();
    modal.open();
    await modal.destroy();

    expect(destroyed).toHaveBeenCalledWith(expect.objectContaining({ detail: { component: modal } }));
    expect(modal.state).toBe("unmounted");
    expect(root.dataset.omState).toBe("closed");
  });

  it("destroy() finishes a close that is still waiting on its transition", async () => {
    // close() 读到 CSS 过渡时长就只是"安排"关闭；紧接着的 stop() 触发清理，
    // 而清理把那个定时器取消掉，于是 finishClose 永远不执行：
    // 面板留在屏幕上、状态卡在 closing、aria-modal 还宣称自己是打开的对话框。
    document.body.innerHTML = `<section id="m" hidden><div data-om-modal-content></div></section>`;
    const root = document.querySelector<HTMLElement>("#m")!;
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      transitionDuration: "0.3s",
      transitionDelay: "0s",
      animationDuration: "0s",
      animationDelay: "0s"
    } as unknown as CSSStyleDeclaration);

    const modal = new Modal(root);
    await modal.start();
    modal.open();
    await modal.destroy();

    expect(root.hidden).toBe(true);
    expect(root.dataset.omState).toBe("closed");
    expect(root.getAttribute("aria-modal")).toBeNull();
    expect(root.getAttribute("aria-hidden")).toBe("true");
    expect(document.querySelectorAll("[data-om-modal-backdrop]")).toHaveLength(0);
  });

  it("control - with no transition destroy() already closed correctly", async () => {
    document.body.innerHTML = `<section id="m" hidden><div data-om-modal-content></div></section>`;
    const root = document.querySelector<HTMLElement>("#m")!;
    const modal = new Modal(root);
    await modal.start();
    modal.open();
    await modal.destroy();

    expect(root.hidden).toBe(true);
    expect(root.dataset.omState).toBe("closed");
  });
});
