import type { AxiosRequestConfig } from "axios";
import { closest, collectIncludedParams, queryAllSelfOrDescendants, querySelfOrDescendant } from "../dom/helpers";
import type { HttpClient, HttpMethod } from "../http/client";
import type { Page } from "../page/page";
import type { PageRegistry } from "../page/registry";
import { TransitionService, type TransitionName } from "../services/transitions";
import {
  bindResponseOperationLifecycle,
  type DefaultApiResponse,
  showDefaultResponseMessage,
  showResponseActionFailure
} from "./response-actions";

export interface StartActionsOptions {
  http: HttpClient;
  pageRegistry: PageRegistry;
  root?: Document | HTMLElement;
  confirm?: ActionConfirmHandler;
  transition?: TransitionName;
  transitions?: TransitionService;
  validate?: boolean;
}

export interface RunActionOptions {
  http: HttpClient;
  pageRegistry?: PageRegistry;
  params?: ActionParams;
  root?: Document | HTMLElement;
  confirm?: ActionConfirmHandler;
  signal?: AbortSignal;
  submitter?: HTMLElement | null;
  transition?: TransitionName;
  transitions?: TransitionService;
  validate?: boolean;
}

export interface ActionRequestContextDetail {
  method: HttpMethod;
  params: ActionParams;
  submitter?: HTMLElement;
  trigger: HTMLElement;
  url: string;
}

export interface ActionSuccessDetail extends ActionRequestContextDetail {
  response: DefaultApiResponse;
}

export interface ActionErrorDetail extends ActionRequestContextDetail {
  error: unknown;
}

export interface ActionInvalidDetail {
  controls: HTMLElement[];
  form: HTMLFormElement;
  method: HttpMethod;
  trigger: HTMLElement;
  url?: string;
}

export interface ActionToggleDetail {
  target: HTMLElement;
  trigger: HTMLElement;
  visible: boolean;
}

export type ActionCompleteDetail = ActionSuccessDetail | ActionErrorDetail;
export type ActionConfirmHandler = (message: string) => boolean | Promise<boolean>;
export type ActionParams = Record<string, string | string[]>;

interface ActiveAction {
  controller: AbortController;
  disabledControls?: Array<{
    element: DisableableElement;
    previousDisabled: boolean;
  }>;
  loadingClasses?: string[];
  previousDisabled?: boolean;
}

type ActionValidationDetail = Pick<ActionInvalidDetail, "controls" | "form" | "trigger">;
type DisableableElement = HTMLButtonElement | HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

const TRANSITION_NAMES = new Set<TransitionName>(["collapse", "fade", "none", "scale", "slide"]);

interface ActionContext {
  activeActions?: Map<HTMLElement, ActiveAction>;
  confirm: ActionConfirmHandler;
  http: HttpClient;
  isStopped?: () => boolean;
  params?: ActionParams;
  pageRegistry: PageRegistry;
  root: Document | HTMLElement;
  signal?: AbortSignal;
  submitter?: HTMLElement | null;
  transition?: TransitionName;
  transitions: TransitionService;
  validate: boolean;
}

export function startActions(options: StartActionsOptions): () => void {
  const root = options.root ?? document;
  const confirmFn = options.confirm ?? window.confirm.bind(window);
  const transitions = options.transitions ?? new TransitionService();
  const activeActions = new Map<HTMLElement, ActiveAction>();
  const activeTimers = new Set<number>();
  let stopped = false;
  const context: ActionContext = {
    activeActions,
    confirm: confirmFn,
    http: options.http,
    pageRegistry: options.pageRegistry,
    isStopped: () => stopped,
    root,
    ...(options.transition ? { transition: options.transition } : {}),
    transitions,
    validate: options.validate ?? true
  };

  const clickListener = async (event: Event) => {
    if (stopped) return;

    const target = event.target;
    if (!(target instanceof Element)) return;

    const trigger = closest(target, "[data-om-action]", root);
    if (!trigger) return;
    if (trigger instanceof HTMLFormElement) return;

    event.preventDefault();
    await executeAction(trigger, context);
  };

  const submitCaptureListener = (event: Event) => {
    // Turbo Frame handles bubbling submissions before document. Mark ownership
    // early, but leave execution in bubbling so component guards still run first.
    const form = event.target;
    if (form instanceof HTMLFormElement && form.hasAttribute("data-om-action")) {
      form.setAttribute("data-turbo", "false");
    }
  };

  const submitListener = async (event: Event) => {
    if (stopped) return;

    const target = event.target;
    if (!(target instanceof Element)) return;

    const trigger = closest<HTMLFormElement>(target, "form[data-om-action]", root);
    if (!trigger) return;

    event.preventDefault();
    const submitter = eventSubmitter(event);
    await executeAction(trigger, {
      ...context,
      ...(submitter ? { submitter } : {}),
    });
  };

  root.addEventListener("click", clickListener);
  root.addEventListener("submit", submitCaptureListener, true);
  root.addEventListener("submit", submitListener);
  startRefreshIntervals(root, context, activeTimers);
  return () => {
    if (stopped) return;
    stopped = true;
    root.removeEventListener("click", clickListener);
    root.removeEventListener("submit", submitCaptureListener, true);
    root.removeEventListener("submit", submitListener);
    for (const timer of activeTimers) {
      window.clearInterval(timer);
    }
    activeTimers.clear();
    for (const [trigger, activeAction] of activeActions) {
      activeAction.controller.abort();
      finishPending(trigger, activeAction);
    }
    activeActions.clear();
  };
}

export function runAction(trigger: HTMLElement, options: RunActionOptions): Promise<DefaultApiResponse | null> {
  if (!options.pageRegistry) throw new Error("Remote data-om-action requires a PageRegistry");
  return executeAction(trigger, {
    confirm: options.confirm ?? window.confirm.bind(window),
    http: options.http,
    pageRegistry: options.pageRegistry,
    ...(options.params ? { params: options.params } : {}),
    root: options.root ?? document,
    ...(options.signal ? { signal: options.signal } : {}),
    ...(options.submitter ? { submitter: options.submitter } : {}),
    ...(options.transition ? { transition: options.transition } : {}),
    transitions: options.transitions ?? new TransitionService(),
    validate: options.validate ?? true
  });
}

async function executeAction(trigger: HTMLElement, context: ActionContext): Promise<DefaultApiResponse | null> {
  const action = trigger.dataset.omAction;
  if (!action) return null;
  if (action === "toggle") {
    await toggleAction(trigger, context);
    return null;
  }
  const method = actionMethod(action, trigger, context.submitter);
  const url = actionUrl(trigger, context.submitter);

  if (context.activeActions?.has(trigger) || trigger.dataset.omLoading === "true") return null;
  if (context.signal?.aborted || context.isStopped?.()) return null;

  const invalidDetail = validateAction(trigger, context.validate, context.submitter);
  if (invalidDetail) {
    dispatchActionEvent(trigger, "om:action:invalid", { ...invalidDetail, method, ...(url ? { url } : {}) });
    return null;
  }

  const confirmMessage = actionConfirmMessage(trigger, context.submitter);
  if (confirmMessage && !(await context.confirm(confirmMessage))) return null;

  const originPage = context.pageRegistry.current;
  if (!originPage || !pageContains(originPage, trigger)) {
    throw new Error("Remote data-om-action requires a mounted Page containing its source");
  }

  if (!url) throw new Error("data-om-url, href, formaction, or form action is required");
  const params = mergeActionParams(actionIncludeParams(context.root, trigger), context.params ?? {});
  const detailContext: ActionRequestContextDetail = {
    method,
    params,
    ...(context.submitter instanceof HTMLElement ? { submitter: context.submitter } : {}),
    trigger,
    url
  };

  const controller = new AbortController();
  const abortController = () => controller.abort();
  context.signal?.addEventListener("abort", abortController, { once: true });
  const cleanupOperation = bindResponseOperationLifecycle(controller, originPage, trigger);
  const activeAction = startPending(trigger, controller, context.root);
  context.activeActions?.set(trigger, activeAction);
  dispatchActionEvent(trigger, "om:action:request", detailContext);

  try {
    let response: DefaultApiResponse;
    try {
      response = await requestApiResponse(
        context.http,
        method,
        url,
        trigger,
        { signal: controller.signal },
        {
          params,
          ...(context.submitter ? { submitter: context.submitter } : {})
        }
      );
    } catch (error) {
      if (controller.signal.aborted || context.isStopped?.()) return null;
      await showResponseActionFailure(originPage, trigger, error);
      trigger.dataset.omError = "true";
      dispatchActionEvent(trigger, "om:action:error", { ...detailContext, error });
      dispatchActionEvent(trigger, "om:action:complete", { ...detailContext, error });
      return null;
    }

    if (
      controller.signal.aborted
      || context.isStopped?.()
      || context.pageRegistry.current !== originPage
      || !trigger.isConnected
      || !pageContains(originPage, trigger)
    ) return null;

    try {
      await showDefaultResponseMessage(originPage, response, trigger);
      await originPage.responseActions.run(response, trigger, controller.signal);
    } catch (error) {
      if (controller.signal.aborted) return null;
      await showResponseActionFailure(originPage, trigger, error);
      trigger.dataset.omError = "true";
      dispatchActionEvent(trigger, "om:action:error", { ...detailContext, error });
      dispatchActionEvent(trigger, "om:action:complete", { ...detailContext, error });
      return null;
    }

    const successDetail = { ...detailContext, response };
    dispatchActionEvent(trigger, "om:action:success", successDetail);
    dispatchConfiguredSuccessEvent(trigger, successDetail);
    dispatchActionEvent(trigger, "om:action:complete", successDetail);
    return response;
  } finally {
    finishPending(trigger, activeAction);
    cleanupOperation();
    context.signal?.removeEventListener("abort", abortController);
    context.activeActions?.delete(trigger);
  }
}

function actionMethod(action: string, trigger: HTMLElement, submitter?: HTMLElement | null): HttpMethod {
  const normalizedAction = action.toLowerCase();
  const method =
    submitterMethod(submitter) ??
    (normalizedAction === "submit" ? formMethod(trigger, submitter) : normalizedAction === "refresh" ? "get" : normalizedAction);
  if (method === "get" || method === "post" || method === "put" || method === "patch" || method === "delete") {
    return method;
  }

  throw new Error(`Unsupported data-om-action: ${action}`);
}

function submitterMethod(submitter?: HTMLElement | null): string | undefined {
  if (!isSubmitter(submitter)) return undefined;
  const method = submitter.getAttribute("formmethod");
  return method ? method.toLowerCase() : undefined;
}

function formMethod(trigger: HTMLElement, submitter?: HTMLElement | null): string | undefined {
  const form = isSubmitter(submitter) ? submitter.form : actionForm(trigger);
  if (!form) return undefined;
  return (form.getAttribute("method") || "get").toLowerCase();
}

function actionUrl(trigger: HTMLElement, submitter?: HTMLElement | null): string | null {
  if (trigger.dataset.omUrl) return trigger.dataset.omUrl;

  if (trigger instanceof HTMLAnchorElement) {
    return trigger.getAttribute("href");
  }

  if (isSubmitter(submitter)) {
    return submitter.getAttribute("formaction") || submitter.form?.getAttribute("action") || null;
  }

  if (trigger instanceof HTMLButtonElement || trigger instanceof HTMLInputElement) {
    return trigger.getAttribute("formaction") || trigger.form?.getAttribute("action") || null;
  }

  if (trigger instanceof HTMLFormElement) {
    return trigger.getAttribute("action");
  }

  return null;
}

function startRefreshIntervals(
  root: Document | HTMLElement,
  context: ActionContext,
  activeTimers: Set<number>
): void {
  for (const trigger of queryAllSelfOrDescendants<HTMLElement>(root, "[data-om-action][data-om-refresh-interval]")) {
    const interval = refreshInterval(trigger);
    if (interval === undefined) continue;

    const timer = window.setInterval(() => {
      if (!rootContains(context.root, trigger)) {
        window.clearInterval(timer);
        activeTimers.delete(timer);
        return;
      }

      void executeAction(trigger, context);
    }, interval);
    activeTimers.add(timer);
  }
}

function refreshInterval(trigger: HTMLElement): number | undefined {
  const value = Number.parseInt(trigger.dataset.omRefreshInterval ?? "", 10);
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

function rootContains(root: Document | HTMLElement, element: HTMLElement): boolean {
  const rootElement = root instanceof Document ? root.documentElement : root;
  return rootElement.contains(element);
}

async function requestApiResponse(
  http: HttpClient,
  method: HttpMethod,
  url: string,
  trigger: HTMLElement,
  config: AxiosRequestConfig,
  context: Pick<ActionContext, "params" | "submitter">
): Promise<DefaultApiResponse> {
  const formData = actionFormData(trigger, context.params, context.submitter);
  const data = method === "get" || method === "delete" ? undefined : formData ?? {};
  const requestConfig =
    formData && (method === "get" || method === "delete")
      ? { ...config, params: formDataToSearchParams(formData) }
      : config;

  if (http.requestJson) {
    return await http.requestJson<DefaultApiResponse>(method, url, data, requestConfig);
  }

  if (method === "get") return await http.getJson<DefaultApiResponse>(url, requestConfig);
  if (method === "post") return await http.postJson<DefaultApiResponse>(url, data, requestConfig);

  const response = await http.axios.request<DefaultApiResponse>({
    ...requestConfig,
    method,
    url,
    data
  });
  return response.data;
}

function actionFormData(
  trigger: HTMLElement,
  params: ActionParams | undefined,
  submitter?: HTMLElement | null
): FormData | undefined {
  const form = actionForm(trigger);

  const actionSubmitter = form ? resolveActionSubmitter(trigger, submitter) : undefined;
  const fallbackBase = actionSubmitter && form ? new FormData(form) : undefined;
  if (!form && !hasActionParams(params)) return undefined;

  const formData = form ? (actionSubmitter ? new FormData(form, actionSubmitter) : new FormData(form)) : new FormData();
  if (actionSubmitter && fallbackBase) appendSubmitterFallback(formData, fallbackBase, actionSubmitter);
  appendActionParams(formData, params);
  return formData;
}

function actionForm(trigger: HTMLElement): HTMLFormElement | null {
  if (trigger instanceof HTMLFormElement) {
    return trigger;
  }

  if (trigger instanceof HTMLButtonElement || trigger instanceof HTMLInputElement) {
    return trigger.form;
  }

  return null;
}

function resolveActionSubmitter(
  trigger: HTMLElement,
  submitter?: HTMLElement | null
): HTMLButtonElement | HTMLInputElement | undefined {
  if (isSubmitter(submitter) && submitter.form === actionForm(trigger)) return submitter;

  if (trigger instanceof HTMLButtonElement) {
    const type = (trigger.getAttribute("type") ?? "submit").toLowerCase();
    return type === "submit" ? trigger : undefined;
  }

  if (trigger instanceof HTMLInputElement) {
    const type = trigger.type.toLowerCase();
    return type === "submit" || type === "image" ? trigger : undefined;
  }

  return undefined;
}

function validateAction(
  trigger: HTMLElement,
  validate: boolean,
  submitter?: HTMLElement | null
): ActionValidationDetail | null {
  if (!validate) return null;

  const form = actionForm(trigger);
  if (!form) return null;

  const actionSubmitter = resolveActionSubmitter(trigger, submitter);
  if (form.noValidate || actionSubmitter?.formNoValidate) return null;

  const valid = typeof form.reportValidity === "function" ? form.reportValidity() : form.checkValidity();
  if (valid) return null;

  return {
    controls: invalidControls(form),
    form,
    trigger
  };
}

function actionConfirmMessage(trigger: HTMLElement, submitter?: HTMLElement | null): string | undefined {
  return submitter?.dataset.omConfirm || trigger.dataset.omConfirm || actionForm(trigger)?.dataset.omConfirm;
}

function formDataToSearchParams(formData: FormData): URLSearchParams {
  const params = new URLSearchParams();
  for (const [name, value] of formData) {
    if (typeof value === "string") {
      params.append(name, value);
    }
  }
  return params;
}

function actionIncludeParams(root: Document | HTMLElement, trigger: HTMLElement): ActionParams | undefined {
  const params = collectIncludedParams(root, trigger.dataset.omInclude);
  return Object.keys(params).length > 0 ? params : undefined;
}

function mergeActionParams(...sources: Array<ActionParams | undefined>): ActionParams {
  const params: ActionParams = {};
  for (const source of sources) {
    if (!source) continue;
    for (const [name, value] of Object.entries(source)) {
      params[name] = Array.isArray(value) ? [...value] : value;
    }
  }
  return params;
}

function hasActionParams(params: ActionParams | undefined): boolean {
  return Boolean(params && Object.keys(params).length > 0);
}

function appendActionParams(formData: FormData, params: ActionParams | undefined): void {
  if (!params) return;

  for (const [name, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        formData.append(name, item);
      }
      continue;
    }

    formData.append(name, value);
  }
}

function appendSubmitterFallback(formData: FormData, fallbackBase: FormData, submitter: HTMLElement): void {
  if (!(submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement)) return;
  if (!submitter.name) return;

  const nativeCount = formData.getAll(submitter.name).length;
  const baseCount = fallbackBase.getAll(submitter.name).length;
  if (nativeCount === baseCount) formData.append(submitter.name, submitter.value);
}

function eventSubmitter(event: Event): HTMLElement | undefined {
  const submitter = (event as Event & { submitter?: EventTarget | null }).submitter;
  return submitter instanceof HTMLElement ? submitter : undefined;
}

function isSubmitter(element: HTMLElement | null | undefined): element is HTMLButtonElement | HTMLInputElement {
  return element instanceof HTMLButtonElement || element instanceof HTMLInputElement;
}

function actionTransitionName(target: HTMLElement, trigger: HTMLElement, fallback: TransitionName = "none"): TransitionName {
  return elementTransitionName(target, elementTransitionName(trigger, fallback));
}

function elementTransitionName(element: HTMLElement, fallback: TransitionName = "none"): TransitionName {
  const transition = element.dataset.omTransition;
  if (transition && TRANSITION_NAMES.has(transition as TransitionName)) return transition as TransitionName;
  return fallback;
}

async function toggleAction(trigger: HTMLElement, context: ActionContext): Promise<void> {
  const selector = trigger.dataset.omTarget;
  if (!selector) return;

  const target = querySelfOrDescendant<HTMLElement>(context.root, selector);
  if (!target) return;

  const visible = toggleActionVisible(target, trigger);
  setToggleClasses(target, trigger, visible);
  await context.transitions.toggle(target, visible, actionTransitionName(target, trigger, context.transition));
  target.setAttribute("aria-hidden", String(!visible));
  if (!visible) setToggleClasses(target, trigger, visible);

  trigger.setAttribute("aria-expanded", String(visible));
  if (target.id && !trigger.hasAttribute("aria-controls")) trigger.setAttribute("aria-controls", target.id);
  dispatchToggleEvent(trigger, { target, trigger, visible });
}

function toggleActionVisible(target: HTMLElement, trigger: HTMLElement): boolean {
  const mode = trigger.dataset.omToggle;
  if (mode === "show") return true;
  if (mode === "hide") return false;
  return target.hidden;
}

function setToggleClasses(target: HTMLElement, trigger: HTMLElement, visible: boolean): void {
  for (const className of classList(trigger.dataset.omToggleClass)) {
    target.classList.toggle(className, visible);
  }

  for (const className of classList(trigger.dataset.omToggleTriggerClass)) {
    trigger.classList.toggle(className, visible);
  }
}

function classList(value: string | undefined): string[] {
  return value?.split(/\s+/).filter(Boolean) ?? [];
}

function pageContains(page: Page, source: HTMLElement): boolean {
  return page.root !== source && page.root.contains(source);
}

function startPending(trigger: HTMLElement, controller: AbortController, root: Document | HTMLElement): ActiveAction {
  trigger.dataset.omLoading = "true";
  trigger.removeAttribute("data-om-error");
  trigger.setAttribute("aria-busy", "true");

  const activeAction: ActiveAction = { controller };
  const loadingClasses = classList(trigger.dataset.omLoadingClass);
  if (loadingClasses.length > 0) {
    trigger.classList.add(...loadingClasses);
    activeAction.loadingClasses = loadingClasses;
  }

  if (isDisableable(trigger)) {
    activeAction.previousDisabled = trigger.disabled;
    trigger.disabled = true;
  }

  const disabledControls = disableActionTargets(root, trigger);
  if (disabledControls) activeAction.disabledControls = disabledControls;
  return activeAction;
}

function finishPending(trigger: HTMLElement, activeAction: ActiveAction): void {
  trigger.removeAttribute("data-om-loading");
  trigger.setAttribute("aria-busy", "false");
  if (activeAction.loadingClasses) trigger.classList.remove(...activeAction.loadingClasses);

  if (isDisableable(trigger) && activeAction.previousDisabled !== undefined) {
    trigger.disabled = activeAction.previousDisabled;
  }

  for (const { element, previousDisabled } of activeAction.disabledControls ?? []) {
    element.disabled = previousDisabled;
  }
}

function disableActionTargets(
  root: Document | HTMLElement,
  trigger: HTMLElement
): Array<{ element: DisableableElement; previousDisabled: boolean }> | undefined {
  const selector = trigger.dataset.omDisable;
  if (!selector) return undefined;

  const controls: Array<{ element: DisableableElement; previousDisabled: boolean }> = [];
  const seen = new Set<DisableableElement>();
  for (const element of queryAllSelfOrDescendants<HTMLElement>(root, selector)) {
    if (!isDisableable(element) || element === trigger || seen.has(element)) continue;
    seen.add(element);
    controls.push({ element, previousDisabled: element.disabled });
    element.disabled = true;
  }
  return controls.length > 0 ? controls : undefined;
}

function isDisableable(element: HTMLElement): element is DisableableElement {
  return (
    element instanceof HTMLButtonElement ||
    element instanceof HTMLInputElement ||
    element instanceof HTMLSelectElement ||
    element instanceof HTMLTextAreaElement
  );
}

function dispatchActionEvent(
  trigger: HTMLElement,
  eventName: string,
  detail: ActionRequestContextDetail | ActionSuccessDetail | ActionErrorDetail | ActionInvalidDetail
): void {
  trigger.dispatchEvent(
    new CustomEvent(eventName, {
      bubbles: true,
      detail
    })
  );
}

function dispatchConfiguredSuccessEvent(trigger: HTMLElement, detail: ActionSuccessDetail): void {
  const eventName = trigger.dataset.omEventSuccess?.trim();
  if (!eventName) return;
  dispatchActionEvent(trigger, eventName, detail);
}

function dispatchToggleEvent(trigger: HTMLElement, detail: ActionToggleDetail): void {
  trigger.dispatchEvent(
    new CustomEvent<ActionToggleDetail>("om:action:toggle", {
      bubbles: true,
      detail
    })
  );
}

interface ValidatableFormControl extends HTMLElement {
  readonly validity: {
    readonly valid: boolean;
  };
  readonly willValidate: boolean;
}

function invalidControls(form: HTMLFormElement): HTMLElement[] {
  return Array.from(form.elements).filter(
    (element): element is ValidatableFormControl =>
      isValidatableFormControl(element) && element.willValidate && !element.validity.valid
  );
}

function isValidatableFormControl(element: Element): element is ValidatableFormControl {
  if (!(element instanceof HTMLElement)) return false;
  const control = element as HTMLElement & {
    validity?: { valid?: unknown };
    willValidate?: unknown;
  };

  return typeof control.willValidate === "boolean" && typeof control.validity?.valid === "boolean";
}
