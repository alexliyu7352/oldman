import type {
  EventStreamLifecycleHandler,
  EventStreamPayloadHandler,
  StopEventStreamHandler
} from "./types";

export const SESSION_INVALIDATED_EVENT = "oldman.session.invalidated";

interface PayloadRegistration {
  handlers: Set<EventStreamPayloadHandler<unknown>>;
  listener: EventListener;
}

interface LifecycleRegistration {
  event: "error" | "open";
  listener: EventListener;
}

/**
 * Thin lifecycle-safe wrapper around the browser's native EventSource.
 *
 * Reconnection and retry timing remain entirely owned by the browser.
 */
export class EventStreamClient {
  private readonly source: EventSource;
  private readonly payloadRegistrations = new Map<string, PayloadRegistration>();
  private readonly lifecycleRegistrations = new Set<LifecycleRegistration>();
  private closed = false;

  constructor(url: string | URL, options: EventSourceInit = {}) {
    this.source = new EventSource(url, options);
  }

  /** Parse one named JSON event and deliver it to an isolated business handler. */
  on<TPayload>(
    eventName: string,
    handler: EventStreamPayloadHandler<TPayload>
  ): StopEventStreamHandler {
    this.requireOpen();
    if (!eventName) {
      throw new TypeError("eventName must not be empty");
    }
    if (typeof handler !== "function") {
      throw new TypeError("handler must be a function");
    }

    let registration = this.payloadRegistrations.get(eventName);
    if (!registration) {
      registration = this.createPayloadRegistration(eventName);
      this.payloadRegistrations.set(eventName, registration);
      this.source.addEventListener(eventName, registration.listener);
    }
    const storedHandler = handler as EventStreamPayloadHandler<unknown>;
    registration.handlers.add(storedHandler);

    let active = true;
    return () => {
      if (!active) return;
      active = false;
      registration?.handlers.delete(storedHandler);
      if (
        registration &&
        registration.handlers.size === 0 &&
        this.payloadRegistrations.get(eventName) === registration
      ) {
        this.source.removeEventListener(eventName, registration.listener);
        this.payloadRegistrations.delete(eventName);
      }
    };
  }

  /** Observe every native open, including opens after an automatic reconnect. */
  onOpen(handler: EventStreamLifecycleHandler): StopEventStreamHandler {
    return this.onLifecycle("open", handler);
  }

  /** Observe native errors without changing EventSource's automatic reconnect behavior. */
  onError(handler: EventStreamLifecycleHandler): StopEventStreamHandler {
    return this.onLifecycle("error", handler);
  }

  /** Permanently close the EventSource and remove all registered listeners. */
  close(): void {
    if (this.closed) return;
    this.closed = true;

    for (const [eventName, registration] of this.payloadRegistrations) {
      this.source.removeEventListener(eventName, registration.listener);
      registration.handlers.clear();
    }
    this.payloadRegistrations.clear();
    for (const registration of this.lifecycleRegistrations) {
      this.source.removeEventListener(registration.event, registration.listener);
    }
    this.lifecycleRegistrations.clear();
    this.source.close();
  }

  private createPayloadRegistration(eventName: string): PayloadRegistration {
    const handlers = new Set<EventStreamPayloadHandler<unknown>>();
    const listener: EventListener = (rawEvent) => {
      const event = rawEvent as MessageEvent<string>;
      const currentHandlers = [...handlers];
      if (eventName === SESSION_INVALIDATED_EVENT) {
        // Capture handlers first, then stop reconnects before handing control to the UI.
        this.close();
      }

      let payload: unknown;
      try {
        payload = JSON.parse(event.data) as unknown;
      } catch (error) {
        console.error(`Failed to parse SSE event ${eventName}`, error);
        return;
      }
      for (const handler of currentHandlers) {
        try {
          handler(payload, event);
        } catch (error) {
          console.error(`SSE handler failed for ${eventName}`, error);
        }
      }
    };
    return { handlers, listener };
  }

  private onLifecycle(
    event: "error" | "open",
    handler: EventStreamLifecycleHandler
  ): StopEventStreamHandler {
    this.requireOpen();
    if (typeof handler !== "function") {
      throw new TypeError("handler must be a function");
    }
    const listener: EventListener = (nativeEvent) => {
      try {
        handler(nativeEvent);
      } catch (error) {
        console.error(`SSE ${event} handler failed`, error);
      }
    };
    const registration = { event, listener } satisfies LifecycleRegistration;
    this.lifecycleRegistrations.add(registration);
    this.source.addEventListener(event, listener);

    let active = true;
    return () => {
      if (!active) return;
      active = false;
      this.source.removeEventListener(event, listener);
      this.lifecycleRegistrations.delete(registration);
    };
  }

  private requireOpen(): void {
    if (this.closed) {
      throw new Error("EventStreamClient is closed");
    }
  }
}
