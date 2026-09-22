import { querySelfOrDescendant } from "../dom/helpers";
import { Page, type NamedPageConstructor, type PageConstructor } from "./page";
import { abortable } from "../services/abort";

const defaultRegistry = new Map<string, PageConstructor>();

/** 使用者的卸载钩子挡住帧渲染的上限；超过就照常放行并报错。 */
const DEFAULT_UNMOUNT_TIMEOUT_MS = 5000;

/**
 * 注册表挂载后端渲染页面根节点前，按需加载对应页面入口。
 */
export type PageLoader = (pageName: string, root: HTMLElement) => void | Promise<void>;

export interface PageRegistryOptions {
  /**
   * 等待一个 Page 卸载完成的上限，默认 5000ms；`0` 或负数表示不设上限。
   *
   * `beforeUnmount()` / `unmount()` 是使用者写的钩子，而 Turbo 的帧渲染被 `preventDefault()`
   * 接管之后，要等这里 resolve 才会 `resume()`。钩子不 settle 就等于帧永远停在 `rendering`，
   * 没有报错、没有降级，而且下一次挂载也会卡在 `pendingUnmount` 上。
   *
   * 超时不是"打断清理"：钩子继续跑，框架只是不再替它挡着渲染，并记一条指名道姓的错误。
   * 把静默卡死换成可见的降级。
   */
  unmountTimeoutMs?: number;
}

export interface PageRegistryMountOptions {
  loadPage?: PageLoader;
  /** Used when the entry name is still unknown after `loadPage`; a warning names the missing entry. */
  fallbackPage?: PageConstructor;
  logger?: { warn(message: string, ...args: unknown[]): void };
}

export class PageRegistry {
  private readonly pages = new Map<string, PageConstructor>();
  private readonly unmountTimeoutMs: number;
  private currentPage: Page | null = null;
  private pendingMount: AbortController | null = null;
  private pendingUnmount: Promise<void> | null = null;

  constructor(options: PageRegistryOptions = {}) {
    this.unmountTimeoutMs = options.unmountTimeoutMs ?? DEFAULT_UNMOUNT_TIMEOUT_MS;
  }

  get current(): Page | null {
    return this.currentPage;
  }

  register(pageClass: NamedPageConstructor): void;
  register(name: string, pageClass: PageConstructor): void;
  register(nameOrClass: string | NamedPageConstructor, pageClass?: PageConstructor): void {
    const registration = resolvePageRegistration(nameOrClass, pageClass);
    this.pages.set(registration.name, registration.pageClass);
  }

  async mount(scope: ParentNode = document, options: PageRegistryMountOptions = {}): Promise<Page | null> {
    const root = querySelfOrDescendant<HTMLElement>(scope, "[data-om-page]");
    if (!root) return null;

    const pageName = root.dataset.omPage;
    if (!pageName) return null;

    if (this.currentPage?.root === root) {
      return this.currentPage;
    }
    // Cancel before waiting: a slow import must never hold up the next navigation.
    const previousUnmount = this.unmount();
    const controller = new AbortController();
    this.pendingMount = controller;
    const { signal } = controller;
    let page: Page | null = null;
    try {
      await abortable(previousUnmount, signal);
      signal.throwIfAborted();
      let PageClass = this.pages.get(pageName) ?? defaultRegistry.get(pageName);
      if (!PageClass && options.loadPage) {
        await abortable(Promise.resolve(options.loadPage(pageName, root)), signal);
        signal.throwIfAborted();
        PageClass = this.pages.get(pageName) ?? defaultRegistry.get(pageName);
      }
      if (!PageClass && options.fallbackPage) {
        // A typo in a template must not black out the page: the base page still mounts the shell.
        (options.logger ?? console).warn(`No page registered for ${pageName}; falling back to ${options.fallbackPage.name || "the fallback page"}`);
        PageClass = options.fallbackPage;
      }
      if (!PageClass) throw new Error(`No page registered for ${pageName}`);

      page = new PageClass(root);
      this.currentPage = page;
      page.setState("mounting");
      await abortable(page.beforeMount(), signal);
      signal.throwIfAborted();
      await abortable(page.mount(), signal);
      signal.throwIfAborted();
      await abortable(page.afterMount(), signal);
      signal.throwIfAborted();
      page.setState("mounted");
    } catch (error) {
      // Superseded loads are normal navigation, not runtime startup failures.
      if (signal.aborted) return null;
      const cleanupErrors: unknown[] = [];

      try {
        // Partially mounted Pages also own shell components and subscriptions
        // released by their unmount hooks, not just ComponentManager resources.
        await this.stopCurrentPage();
      } catch (cleanupError) {
        cleanupErrors.push(cleanupError);
      }

      if (signal.aborted) return null;
      page?.setState("failed");
      throw createPageMountError(error, cleanupErrors);
    } finally {
      if (this.pendingMount === controller) this.pendingMount = null;
    }

    return page;
  }

  unmount(): Promise<void> {
    this.pendingMount?.abort();
    this.pendingMount = null;
    return this.stopCurrentPage();
  }

  /** Serialize resource release without cancelling the caller's own error reporting. */
  private stopCurrentPage(): Promise<void> {
    if (!this.currentPage) return this.pendingUnmount ?? Promise.resolve();
    const page = this.currentPage;
    this.currentPage = null;
    page.setState("unmounting");
    const pending = this.unmountPageBeforeDeadline(page).finally(() => {
      if (this.pendingUnmount === pending) this.pendingUnmount = null;
    });
    this.pendingUnmount = pending;
    return pending;
  }

  /**
   * Run this Page's unmount, but stop waiting on it after `unmountTimeoutMs`.
   *
   * The hooks keep running; what the deadline ends is the framework holding the frame render
   * and the next mount hostage to them. A stalled Page is reported by name so the person whose
   * hook it is can find it.
   */
  private async unmountPageBeforeDeadline(page: Page): Promise<void> {
    if (this.unmountTimeoutMs <= 0) return this.unmountPage(page);

    let timer: ReturnType<typeof setTimeout> | undefined;
    const unmounted = this.unmountPage(page);
    // The losing promise still settles later; without this a post-deadline failure would
    // surface as an unhandled rejection with no owner.
    let settledWithError: unknown;
    let settled = false;
    const observed = unmounted.then(
      () => {
        settled = true;
      },
      (error: unknown) => {
        settled = true;
        settledWithError = error;
      }
    );

    await Promise.race([
      observed,
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, this.unmountTimeoutMs);
      })
    ]);
    if (timer !== undefined) clearTimeout(timer);

    if (!settled) {
      page.logger.error(
        `Oldman stopped waiting for page "${page.root.dataset.omPage ?? page.constructor.name}" to unmount after ${this.unmountTimeoutMs}ms; its beforeUnmount/unmount hook has not settled`
      );
      return;
    }
    if (settledWithError !== undefined) throw settledWithError;
  }

  /** Finish only this Page's resources; later mounts wait for this cleanup. */
  private async unmountPage(page: Page): Promise<void> {
    const errors: unknown[] = [];

    try {
      await page.beforeUnmount();
    } catch (error) {
      errors.push(error);
    }

    try {
      await page.unmount();
    } catch (error) {
      errors.push(error);
    }

    try {
      await page.unmountComponents();
    } catch (error) {
      errors.push(error);
    }

    try {
      await page.runCleanup();
    } catch (error) {
      errors.push(error);
    }

    if (errors.length > 0) {
      page.setState("failed");
      throw createPageLifecycleError(errors);
    }

    page.setState("unmounted");
  }
}

export function registerPage(pageClass: NamedPageConstructor): void;
export function registerPage(name: string, pageClass: PageConstructor): void;
export function registerPage(nameOrClass: string | NamedPageConstructor, pageClass?: PageConstructor): void {
  const registration = resolvePageRegistration(nameOrClass, pageClass);
  defaultRegistry.set(registration.name, registration.pageClass);
}

function createPageLifecycleError(errors: unknown[]): unknown {
  if (errors.length === 1) {
    return errors[0];
  }

  return new AggregateError(errors, "Page unmount failed");
}

function createPageMountError(error: unknown, cleanupErrors: unknown[]): unknown {
  if (cleanupErrors.length === 0) {
    return error;
  }

  return new AggregateError([error, ...cleanupErrors], "Page mount failed", { cause: error });
}

function resolvePageRegistration(
  nameOrClass: string | NamedPageConstructor,
  pageClass?: PageConstructor
): { name: string; pageClass: PageConstructor } {
  if (typeof nameOrClass === "string") {
    if (!pageClass) throw new Error(`Page registration for "${nameOrClass}" requires a page class`);
    return { name: nameOrClass, pageClass };
  }

  return { name: nameOrClass.pageName, pageClass: nameOrClass };
}
