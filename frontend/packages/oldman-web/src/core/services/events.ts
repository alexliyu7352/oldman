import type { CleanupRegistry } from "./cleanup";
import { closest, delegate } from "../dom/helpers";

export type DelegatedEventHandler<TEvent extends Event = Event> = (
  event: TEvent,
  matchedElement: Element
) => void;

export type DirectEventHandler<TEvent extends Event = Event> = (event: TEvent) => void;
export type CustomEventTarget = Document | HTMLElement | Window;
export type EmitEventOptions<TDetail = unknown> = Omit<CustomEventInit<TDetail>, "detail">;

export class EventService {
  constructor(
    private readonly root: HTMLElement | Document,
    private readonly cleanup: CleanupRegistry
  ) {}

  listen<TEvent extends Event = Event>(
    target: CustomEventTarget,
    eventName: string,
    handler: DirectEventHandler<TEvent>,
    options?: AddEventListenerOptions
  ): void {
    const listener = (event: Event) => void handler(event as TEvent);
    target.addEventListener(eventName, listener, options);
    this.cleanup.add(() => target.removeEventListener(eventName, listener, options));
  }

  emit<TDetail = unknown>(
    target: CustomEventTarget,
    eventName: string,
    detail?: TDetail,
    options: EmitEventOptions<TDetail> = {}
  ): boolean {
    return target.dispatchEvent(
      new CustomEvent<TDetail>(eventName, {
        bubbles: true,
        ...options,
        detail: detail as TDetail
      })
    );
  }

  on<K extends keyof HTMLElementEventMap>(
    eventName: K,
    selector: string,
    handler: DelegatedEventHandler<HTMLElementEventMap[K]>
  ): void {
    this.cleanup.add(delegate(this.root, eventName, selector, handler));
  }

  onCustom<TDetail = unknown>(
    eventName: string,
    selector: string,
    handler: DelegatedEventHandler<CustomEvent<TDetail>>
  ): void {
    const listener = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;

      const matched = closest<HTMLElement>(target, selector, this.root);
      if (matched) void handler(event as CustomEvent<TDetail>, matched);
    };

    this.root.addEventListener(eventName, listener);
    this.cleanup.add(() => this.root.removeEventListener(eventName, listener));
  }
}
