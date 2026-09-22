export type TransitionName = "fade" | "slide" | "scale" | "collapse" | "none";
export type SwapMode = "outer" | "inner" | "append" | "prepend" | "remove";

export interface SwapOptions {
  mode: SwapMode;
  transition?: TransitionName;
}

export type TransitionCallback<T> = () => T | Promise<T>;

export class TransitionService {
  async enter(element: Element, transition: TransitionName = "fade"): Promise<void> {
    if (transition === "none" || this.prefersReducedMotion()) return;
    await this.run(element, `om-${transition}-enter`);
  }

  async leave(element: Element, transition: TransitionName = "fade"): Promise<void> {
    if (transition === "none" || this.prefersReducedMotion()) return;
    await this.run(element, `om-${transition}-leave`);
  }

  async show(element: HTMLElement, transition: TransitionName = "fade"): Promise<void> {
    element.hidden = false;
    await this.enter(element, transition);
  }

  async hide(element: HTMLElement, transition: TransitionName = "fade"): Promise<void> {
    await this.leave(element, transition);
    element.hidden = true;
  }

  async toggle(element: HTMLElement, visible = element.hidden, transition: TransitionName = "fade"): Promise<void> {
    if (visible) {
      await this.show(element, transition);
      return;
    }

    await this.hide(element, transition);
  }

  async withClasses<T>(element: Element, classNames: string[], callback: TransitionCallback<T>): Promise<T> {
    element.classList.add(...classNames);
    try {
      return await callback();
    } finally {
      element.classList.remove(...classNames);
    }
  }

  toggleClass(element: Element, className: string, force?: boolean): boolean {
    return element.classList.toggle(className, force);
  }

  async swap(target: Element, node: Node, options: SwapOptions): Promise<void> {
    const transition = options.transition ?? "none";

    if (options.mode === "remove") {
      await this.leave(target, transition);
      target.remove();
      return;
    }

    if (options.mode === "outer") {
      await this.leave(target, transition);
      target.replaceWith(node);
      if (node instanceof Element) await this.enter(node, transition);
      return;
    }

    if (options.mode === "inner") {
      target.replaceChildren(node);
      if (node instanceof Element) await this.enter(node, transition);
      return;
    }

    if (options.mode === "append") target.append(node);
    if (options.mode === "prepend") target.prepend(node);
    if (node instanceof Element) await this.enter(node, transition);
  }

  private prefersReducedMotion(): boolean {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  }

  private async run(element: Element, className: string): Promise<void> {
    element.classList.add(className);

    const durationMs = this.transitionDurationMs(element);
    if (durationMs <= 0) {
      await Promise.resolve();
      element.classList.remove(className);
      return;
    }

    await new Promise<void>((resolve) => {
      let done = false;
      let timeoutId: number | undefined;

      const finish = () => {
        if (done) return;
        done = true;
        if (timeoutId) window.clearTimeout(timeoutId);
        element.removeEventListener("animationend", onEnd);
        element.removeEventListener("animationcancel", onEnd);
        element.removeEventListener("transitionend", onEnd);
        element.removeEventListener("transitioncancel", onEnd);
        element.classList.remove(className);
        resolve();
      };

      const onEnd = (event: Event) => {
        if (event.target === element) finish();
      };

      element.addEventListener("animationend", onEnd);
      element.addEventListener("animationcancel", onEnd);
      element.addEventListener("transitionend", onEnd);
      element.addEventListener("transitioncancel", onEnd);
      timeoutId = window.setTimeout(finish, durationMs + 50);
    });
  }

  private transitionDurationMs(element: Element): number {
    const style = window.getComputedStyle?.(element);
    if (!style) return 0;

    return Math.max(
      maxTimeListMs(style.transitionDuration, style.transitionDelay),
      maxTimeListMs(style.animationDuration, style.animationDelay)
    );
  }
}

export function maxTimeListMs(durations: string, delays: string): number {
  const durationValues = durations.split(",").map(timeToMs);
  const delayValues = delays.split(",").map(timeToMs);

  return durationValues.reduce((max, duration, index) => {
    const delay = delayValues[index] ?? delayValues[delayValues.length - 1] ?? 0;
    return Math.max(max, duration + delay);
  }, 0);
}

function timeToMs(value: string): number {
  const trimmed = value.trim();
  if (!trimmed) return 0;
  if (trimmed.endsWith("ms")) return Number.parseFloat(trimmed);
  if (trimmed.endsWith("s")) return Number.parseFloat(trimmed) * 1000;
  return Number.parseFloat(trimmed) || 0;
}
