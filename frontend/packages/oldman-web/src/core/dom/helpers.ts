export type DelegatedDomHandler<TEvent extends Event = Event> = (
  event: TEvent,
  matchedElement: HTMLElement
) => void | Promise<void>;

export type StopDomListener = () => void;
export type DomParams = Record<string, string | string[]>;

export interface FormParamOptions {
  submitter?: HTMLElement | null | undefined;
}

/**
 * Escape text for interpolation into an HTML attribute or text node.
 *
 * Exported because it was needed outside the class that had it: the admin app declared a
 * byte-identical copy, since the original was a `protected` member of DashboardTopbar
 * and unreachable from a free function. Two copies of an escaper is how one of them
 * eventually stops matching the other.
 */
export function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function query<TElement extends Element = HTMLElement>(
  root: ParentNode,
  selector: string
): TElement | null {
  return root.querySelector<TElement>(selector);
}

export function querySelfOrDescendant<TElement extends Element = HTMLElement>(
  root: ParentNode,
  selector: string
): TElement | null {
  if (root instanceof Element && root.matches(selector)) return root as TElement;
  return root.querySelector<TElement>(selector);
}

export function queryAllSelfOrDescendants<TElement extends Element = HTMLElement>(
  root: ParentNode,
  selector: string
): TElement[] {
  const elements: TElement[] = [];
  if (root instanceof Element && root.matches(selector)) elements.push(root as TElement);
  elements.push(...Array.from(root.querySelectorAll<TElement>(selector)));
  return elements;
}

export function mustQuery<TElement extends Element = HTMLElement>(root: ParentNode, selector: string): TElement {
  const element = query<TElement>(root, selector);
  if (!element) throw new Error(`Element not found: ${selector}`);
  return element;
}

export function closest<TElement extends Element = HTMLElement>(
  element: Element,
  selector: string,
  boundary?: ParentNode
): TElement | null {
  const match = element.closest<TElement>(selector);
  if (!match) return null;
  if (!boundary) return match;

  const boundaryElement = boundary instanceof Document ? boundary.documentElement : boundary;
  return boundaryElement.contains(match) ? match : null;
}

export function delegate<K extends keyof HTMLElementEventMap>(
  root: Document | HTMLElement,
  eventName: K,
  selector: string,
  handler: DelegatedDomHandler<HTMLElementEventMap[K]>
): StopDomListener {
  const listener = (event: Event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const matched = closest<HTMLElement>(target, selector, root);
    if (matched) void handler(event as HTMLElementEventMap[K], matched);
  };

  root.addEventListener(eventName, listener);
  return () => root.removeEventListener(eventName, listener);
}

export interface DataReader {
  (element: HTMLElement, name: string, fallback?: string): string | undefined;
  boolean(element: HTMLElement, name: string, fallback?: boolean): boolean;
  integer(element: HTMLElement, name: string, fallback?: number): number | undefined;
  json<TValue = unknown>(element: HTMLElement, name: string, fallback?: TValue): TValue | undefined;
  list(element: HTMLElement, name: string, fallback?: string[], separator?: string): string[];
  number(element: HTMLElement, name: string, fallback?: number): number | undefined;
  string(element: HTMLElement, name: string, fallback?: string): string | undefined;
}

export const data: DataReader = Object.assign(
  (element: HTMLElement, name: string, fallback?: string): string | undefined => dataValue(element, name) ?? fallback,
  {
    boolean(element: HTMLElement, name: string, fallback = false): boolean {
      const value = dataValue(element, name);
      if (value === undefined) return fallback;
      return value === "true" || value === "1";
    },
    integer(element: HTMLElement, name: string, fallback?: number): number | undefined {
      const value = dataValue(element, name);
      if (value === undefined || value === "") return fallback;
      const parsed = Number(value);
      return Number.isInteger(parsed) ? parsed : fallback;
    },
    json<TValue = unknown>(element: HTMLElement, name: string, fallback?: TValue): TValue | undefined {
      const value = dataValue(element, name);
      if (value === undefined || value === "") return fallback;

      try {
        return JSON.parse(value) as TValue;
      } catch {
        return fallback;
      }
    },
    list(element: HTMLElement, name: string, fallback: string[] = [], separator = ","): string[] {
      const value = dataValue(element, name);
      if (value === undefined) return fallback;
      if (value === "") return [];
      return value
        .split(separator)
        .map((item) => item.trim())
        .filter(Boolean);
    },
    number(element: HTMLElement, name: string, fallback?: number): number | undefined {
      const value = dataValue(element, name);
      if (value === undefined || value === "") return fallback;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    },
    string(element: HTMLElement, name: string, fallback?: string): string | undefined {
      return dataValue(element, name) ?? fallback;
    }
  }
);

function dataValue(element: HTMLElement, name: string): string | undefined {
  return element.dataset[datasetKey(name)];
}

function datasetKey(name: string): string {
  if (!name.includes("-")) return name;
  return name.replace(/-([a-z0-9])/gi, (_, char: string) => char.toUpperCase());
}

export function attr(element: Element, name: string, value: string | number | boolean | null | undefined): void {
  if (value === null || value === undefined) {
    element.removeAttribute(name);
    return;
  }

  element.setAttribute(name, String(value));
}

export function setClasses(element: Element, classes: Record<string, boolean>): void {
  for (const [className, enabled] of Object.entries(classes)) {
    element.classList.toggle(className, enabled);
  }
}

/**
 * Index a roving-focus list should move to for a navigation key, or null for any other key.
 * Arrows stop at either end instead of wrapping; Home and End jump to the ends.
 */
export function listNavigationIndex(key: string, current: number, length: number): number | null {
  if (length === 0) return null;
  const last = length - 1;
  if (key === "Home") return 0;
  if (key === "End") return last;
  if (key === "ArrowDown") return Math.min(last, current + 1);
  if (key === "ArrowUp") return Math.max(0, current - 1);
  return null;
}

export function setHidden(element: HTMLElement, hidden: boolean): void {
  element.hidden = hidden;
  element.setAttribute("aria-hidden", String(hidden));
}

export function collectFormParams(form: HTMLFormElement, options: FormParamOptions = {}): DomParams {
  const params: DomParams = {};
  addFormParams(params, form, options);
  return params;
}

export function addFormParams(params: DomParams, form: HTMLFormElement, options: FormParamOptions = {}): void {
  for (const [name, value] of createFormData(form, options.submitter)) {
    if (typeof value === "string") addDomParam(params, name, value);
  }
}

export function collectElementParams(element: HTMLElement): DomParams {
  const params: DomParams = {};
  addElementParams(params, element);
  return params;
}

export function addElementParams(params: DomParams, element: HTMLElement): void {
  if (element instanceof HTMLFormElement) {
    addFormParams(params, element);
    return;
  }

  if (isNamedFormControl(element) && !element.disabled) {
    addControlParam(params, element);
  }
}

export function collectIncludedParams(root: Document | HTMLElement, selector: string | undefined): DomParams {
  const params: DomParams = {};
  if (!selector) return params;

  for (const element of queryAllSelfOrDescendants<HTMLElement>(root, selector)) {
    addElementParams(params, element);
  }
  return params;
}

export function addDomParam(params: DomParams, name: string, value: string): void {
  const current = params[name];
  if (current === undefined) {
    params[name] = value;
    return;
  }

  params[name] = Array.isArray(current) ? [...current, value] : [current, value];
}

export function isNamedFormControl(
  element: HTMLElement
): element is HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement {
  return (
    (element instanceof HTMLInputElement ||
      element instanceof HTMLSelectElement ||
      element instanceof HTMLTextAreaElement) &&
    element.name.length > 0
  );
}

function addControlParam(
  params: DomParams,
  control: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
): void {
  if (control instanceof HTMLInputElement && (control.type === "checkbox" || control.type === "radio") && !control.checked) {
    return;
  }

  if (control instanceof HTMLSelectElement && control.multiple) {
    for (const option of Array.from(control.selectedOptions)) {
      addDomParam(params, control.name, option.value);
    }
    return;
  }

  addDomParam(params, control.name, control.value);
}

function createFormData(form: HTMLFormElement, submitter?: HTMLElement | null): FormData {
  if (!(submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement)) {
    return new FormData(form);
  }

  const fallbackBase = new FormData(form);
  try {
    const formData = new FormData(form, submitter);
    appendSubmitterFallback(formData, fallbackBase, submitter);
    return formData;
  } catch {
    appendSubmitterFallback(fallbackBase, new FormData(form), submitter);
    return fallbackBase;
  }
}

function appendSubmitterFallback(formData: FormData, fallbackBase: FormData, submitter: HTMLButtonElement | HTMLInputElement): void {
  if (!submitter.name) return;

  const nativeCount = formData.getAll(submitter.name).length;
  const baseCount = fallbackBase.getAll(submitter.name).length;
  if (nativeCount === baseCount) formData.append(submitter.name, submitter.value);
}

/** 用 CSS.escape 构造选择器；环境缺失时只转义会破坏属性选择器的两个字符。 */
export function cssEscape(value: string): string {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
}

/** 读取一个整数属性；缺失或不是整数时返回 undefined，让调用方用自己的默认值。 */
export function integerAttribute(element: Element, name: string): number | undefined {
  const value = element.getAttribute(name);
  if (!value) return undefined;

  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : undefined;
}
