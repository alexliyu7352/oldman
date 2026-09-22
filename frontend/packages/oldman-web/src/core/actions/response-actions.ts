import type { Page } from "../page/page";
import { abortable, abortError } from "../services/abort";

export const ApiResponseAction = {
  FEEDBACK: "feedback",
  REPLACE_HTML: "replace_html",
  CLOSE_MODAL: "close_modal",
  RELOAD_TABLE: "reload_table",
  REDIRECT: "redirect"
} as const;

export type ApiResponseActionName = typeof ApiResponseAction[keyof typeof ApiResponseAction];
export type FeedbackMode = "alert" | "toast";
export type HtmlSwap = "inner" | "outer";

export interface ResponseAction {
  action: string;
  target?: string | null;
  data?: unknown;
  [field: string]: unknown;
}

export interface FeedbackAction extends ResponseAction {
  action: "feedback";
  mode?: FeedbackMode;
  title: string;
  text?: string | null;
  icon?: string | null;
}

export interface ReplaceHtmlAction extends ResponseAction {
  action: "replace_html";
  html: string;
  swap?: HtmlSwap | null;
}

export interface CloseModalAction extends ResponseAction {
  action: "close_modal";
}

export interface ReloadTableAction extends ResponseAction {
  action: "reload_table";
  target: string;
}

export interface RedirectAction extends ResponseAction {
  action: "redirect";
  url: string;
  delay_ms?: number;
}

export interface DefaultApiResponse {
  error_code: number;
  message: string;
  data: Record<string, unknown>;
  actions: ResponseAction[];
}

export interface DefaultApiFormResponse extends DefaultApiResponse {
  errors: Record<string, string>;
}

export interface ResponseActionContext {
  readonly response: DefaultApiResponse;
  readonly source: HTMLElement;
  readonly page: Page;
  readonly signal?: AbortSignal;
}

export interface ResponseFeedback {
  alert(...args: any[]): Promise<unknown>;
  toast(...args: any[]): Promise<unknown>;
  close(): void;
}

/** Execute one server response against the Page that issued its request. */
export class ResponseActionRunner {
  constructor(private readonly page: Page) {}

  async run(
    response: DefaultApiResponse,
    source: HTMLElement,
    signal?: AbortSignal
  ): Promise<void> {
    if (source === this.page.root || !this.page.root.contains(source)) {
      throw new Error("Response action source must be inside the current page");
    }
    const context: ResponseActionContext = { response, source, page: this.page, ...(signal ? { signal } : {}) };

    for (const action of response.actions) {
      signal?.throwIfAborted();
      switch (action.action) {
        case ApiResponseAction.FEEDBACK:
          await this.feedback(action as FeedbackAction, context);
          break;
        case ApiResponseAction.REPLACE_HTML:
          await this.replaceHtml(action as ReplaceHtmlAction, context);
          break;
        case ApiResponseAction.CLOSE_MODAL:
          this.closeModal(action as CloseModalAction, context);
          break;
        case ApiResponseAction.RELOAD_TABLE:
          await this.reloadTable(action as ReloadTableAction);
          break;
        case ApiResponseAction.REDIRECT:
          await this.redirect(action as RedirectAction, signal);
          return;
        default:
          if (!await this.page.handleResponseAction(action, context)) {
            throw new Error(`Unknown response action: ${action.action}`);
          }
      }
    }
  }

  private async feedback(action: FeedbackAction, context: ResponseActionContext): Promise<void> {
    const feedback = this.resolveFeedback(action, context);
    const options: Record<string, unknown> = { titleText: action.title };
    if (action.text) options.text = action.text;
    if (action.icon) options.icon = action.icon;

    if ((action.mode ?? "toast") === "toast") {
      feedback.toast(options).catch((error: unknown) => {
        this.page.logger.error("Oldman response toast failed", error);
      });
      return;
    }

    await abortable(feedback.alert(options), context.signal, () => feedback.close());
  }

  private resolveFeedback(action: FeedbackAction, context: ResponseActionContext): ResponseFeedback {
    const feedback = resolveResponseFeedback(this.page, context.source, action.target);
    if (feedback) return feedback;
    throw new Error("Response action requires a mounted Feedback");
  }

  /**
   * 把服务端返回的片段换进 DOM。
   *
   * **`action.html` 按未转义的 HTML 处理，这是设计,不是遗漏。** 框架的模型是服务端用 Jinja
   * 渲染好整段片段(模板默认自动转义)再整块换入;和 Python 侧 `modal_response` 的 docstring
   * 声明的是同一个契约。框架在这里再清洗一遍,等于替使用者决定什么标记算安全——
   * 而使用者要输出一段富文本时就只能绕过框架。产生这段 HTML 的那一侧负责转义。
   */
  private async replaceHtml(action: ReplaceHtmlAction, context: ResponseActionContext): Promise<void> {
    const selector = action.target || context.source.dataset.omTarget;
    const target = selector ? this.target(selector) : context.source;
    const swap = action.swap || parseSwap(context.source.dataset.omSwap) || "inner";

    if (swap === "inner" && target instanceof HTMLFormElement && target === context.source) {
      const replacement = firstForm(action.html);
      if (replacement) {
        await this.page.components.unmountDescendants(target);
        syncAttributes(target, replacement);
        target.replaceChildren(...Array.from(replacement.childNodes));
        await this.page.components.mount(target);
        return;
      }
    }

    if (swap === "inner") {
      await this.page.components.unmountDescendants(target);
      target.innerHTML = action.html;
      await this.page.components.mount(target);
      return;
    }

    const parent = target.parentElement;
    if (!parent) throw new Error("Cannot replace a detached response action target");
    const template = document.createElement("template");
    template.innerHTML = action.html.trim();
    const nodes = Array.from(template.content.childNodes);
    await this.page.components.unmount(target);
    target.replaceWith(...nodes);
    for (const node of nodes) {
      if (node instanceof HTMLElement) await this.page.components.mount(node);
    }
  }

  private closeModal(action: CloseModalAction, context: ResponseActionContext): void {
    const target = action.target
      ? this.target(action.target)
      : context.source.closest<HTMLElement>("[data-om-component='modal']");
    if (!target) throw new Error("Close modal action requires a target or source modal");
    const component = this.page.components.get(target) as unknown;
    if (!hasMethod(component, "close")) throw new Error("Close modal target is not a mounted Modal");
    (component as { close(reason?: string): void }).close("response-action");
  }

  private async reloadTable(action: ReloadTableAction): Promise<void> {
    if (!action.target) throw new Error("Reload table action requires a target");
    const target = this.target(action.target);
    const component = this.page.components.get(target) as unknown;
    if (!hasMethod(component, "reload")) throw new Error("Reload table target is not a mounted Table");
    await (component as { reload(): Promise<void> }).reload();
  }

  private async redirect(action: RedirectAction, signal?: AbortSignal): Promise<void> {
    const delay = action.delay_ms ?? 0;
    if (delay < 0) throw new Error("Redirect delay must not be negative");
    if (delay > 0) await this.delay(delay, signal);
    signal?.throwIfAborted();
    window.location.assign(action.url);
  }

  private delay(milliseconds: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      const finish = () => {
        signal?.removeEventListener("abort", cancel);
        resolve();
      };
      const timer = this.page.timers.timeout(finish, milliseconds);
      const cancel = () => {
        window.clearTimeout(timer);
        reject(abortError());
      };
      if (signal?.aborted) {
        cancel();
        return;
      }
      signal?.addEventListener("abort", cancel, { once: true });
    });
  }

  private target(selector: string): HTMLElement {
    const target = this.page.root.querySelector<HTMLElement>(selector);
    if (!target) throw new Error(`Response action target not found in current page: ${selector}`);
    return target;
  }
}

/** Bind one remote request and its response actions to the source Page and Turbo Frame. */
export function bindResponseOperationLifecycle(
  controller: AbortController,
  page: Page,
  source: HTMLElement
): () => void {
  const abort = () => controller.abort();
  page.signal.addEventListener("abort", abort, { once: true });
  if (page.signal.aborted) controller.abort();

  const frame = source.closest<HTMLElement>("turbo-frame");
  const abortFrame = (event: Event) => {
    if (event.target === frame) controller.abort();
  };
  frame?.addEventListener("turbo:before-fetch-request", abortFrame);
  frame?.addEventListener("turbo:before-frame-render", abortFrame);

  return () => {
    page.signal.removeEventListener("abort", abort);
    frame?.removeEventListener("turbo:before-fetch-request", abortFrame);
    frame?.removeEventListener("turbo:before-frame-render", abortFrame);
  };
}

/** Display the message fallback used by non-Form API actions. */
export async function showDefaultResponseMessage(
  page: Page,
  response: DefaultApiResponse,
  source: HTMLElement
): Promise<void> {
  if (!response.message || response.actions.some((action) => action.action === ApiResponseAction.FEEDBACK)) return;

  let feedback: ResponseFeedback | null;
  try {
    feedback = resolveResponseFeedback(page, source);
  } catch (error) {
    page.logger.error("Oldman response message Feedback is invalid", error);
    return;
  }
  if (!feedback) {
    page.logger.warn("Oldman response message has no mounted Feedback", response.message);
    return;
  }
  if (response.error_code === 0) {
    feedback.toast({ titleText: response.message }).catch((error: unknown) => {
      page.logger.error("Oldman response toast failed", error);
    });
    return;
  }
  await feedback.alert({ icon: "error", titleText: response.message });
}

/** Share request/action failure feedback without fabricating a Form business message. */
export async function showResponseActionFailure(
  page: Page,
  source: HTMLElement,
  error: unknown
): Promise<void> {
  let feedback: ResponseFeedback | null;
  try {
    feedback = resolveResponseFeedback(page, source);
  } catch (feedbackError) {
    page.logger.error("Oldman response action failed", error, feedbackError);
    return;
  }
  if (!feedback) {
    page.logger.error("Oldman response action failed", error);
    return;
  }
  try {
    await feedback.alert({ icon: "error", titleText: page.i18n.t("Request failed") });
  } catch (feedbackError) {
    page.logger.error("Oldman response action failed", error, feedbackError);
  }
}

function sourceFeedbackTarget(source: HTMLElement): string | undefined {
  if (source instanceof HTMLFormElement) return source.dataset.omFeedbackTarget;
  return source.closest<HTMLFormElement>("form")?.dataset.omFeedbackTarget;
}

function resolveResponseFeedback(
  page: Page,
  source: HTMLElement,
  explicitTarget?: string | null
): ResponseFeedback | null {
  const selector = explicitTarget || sourceFeedbackTarget(source);
  if (!selector) return page.feedback;

  const target = page.root.querySelector<HTMLElement>(selector);
  if (!target) throw new Error(`Response feedback target not found in current page: ${selector}`);
  const component = page.components.get(target) as unknown;
  if (!isFeedback(component)) throw new Error(`Response feedback target is not a mounted Feedback: ${selector}`);
  return component;
}

function parseSwap(value: string | undefined): HtmlSwap | undefined {
  return value === "inner" || value === "outer" ? value : undefined;
}

function firstForm(html: string): HTMLFormElement | null {
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  return template.content.firstElementChild instanceof HTMLFormElement
    ? template.content.firstElementChild
    : null;
}

function syncAttributes(target: HTMLElement, source: HTMLElement): void {
  for (const attribute of Array.from(target.attributes)) {
    if (!source.hasAttribute(attribute.name)) target.removeAttribute(attribute.name);
  }
  for (const attribute of Array.from(source.attributes)) {
    target.setAttribute(attribute.name, attribute.value);
  }
}

function isFeedback(value: unknown): value is ResponseFeedback {
  return hasMethod(value, "alert") && hasMethod(value, "toast") && hasMethod(value, "close");
}

function hasMethod<TName extends string>(value: unknown, name: TName): value is Record<TName, (...args: never[]) => unknown> {
  return Boolean(value && typeof value === "object" && typeof (value as Record<string, unknown>)[name] === "function");
}
