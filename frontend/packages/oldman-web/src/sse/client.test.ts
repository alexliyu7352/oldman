import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventStreamClient, SESSION_INVALIDATED_EVENT } from "./client";
import type { SessionInvalidatedPayload } from "./types";

class FakeEventSource extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readonly CONNECTING = FakeEventSource.CONNECTING;
  readonly OPEN = FakeEventSource.OPEN;
  readonly CLOSED = FakeEventSource.CLOSED;
  readonly url: string;
  readonly withCredentials: boolean;
  readyState = FakeEventSource.CONNECTING;
  closeCalls = 0;

  constructor(url: string | URL, options: EventSourceInit = {}) {
    super();
    this.url = String(url);
    this.withCredentials = options.withCredentials ?? false;
    FakeEventSource.instances.push(this);
  }

  close(): void {
    this.closeCalls += 1;
    this.readyState = FakeEventSource.CLOSED;
  }

  emitMessage(eventName: string, data: string): void {
    this.dispatchEvent(new MessageEvent(eventName, { data }));
  }
}

describe("EventStreamClient", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("parses named JSON events and returns an idempotent remover", () => {
    const client = new EventStreamClient("/events", { withCredentials: true });
    const source = currentSource();
    const handler = vi.fn();
    const stop = client.on<{ value: number }>("app.status", handler);

    source.emitMessage("app.status", '{"value":7}');
    stop();
    stop();
    source.emitMessage("app.status", '{"value":8}');

    expect(source.url).toBe("/events");
    expect(source.withCredentials).toBe(true);
    expect(handler).toHaveBeenCalledOnce();
    expect(handler.mock.calls[0]?.[0]).toEqual({ value: 7 });
    expect(handler.mock.calls[0]?.[1]).toBeInstanceOf(MessageEvent);
  });

  it("reports every native open, including reconnects, until removed", () => {
    const client = new EventStreamClient("/events");
    const source = currentSource();
    const handler = vi.fn();
    const stop = client.onOpen(handler);

    source.dispatchEvent(new Event("open"));
    source.dispatchEvent(new Event("open"));
    stop();
    source.dispatchEvent(new Event("open"));

    expect(handler).toHaveBeenCalledTimes(2);
  });

  it("observes native errors without closing or creating a retry timer", () => {
    const timer = vi.spyOn(globalThis, "setTimeout");
    const client = new EventStreamClient("/events");
    const source = currentSource();
    const handler = vi.fn();
    client.onError(handler);

    source.dispatchEvent(new Event("error"));

    expect(handler).toHaveBeenCalledOnce();
    expect(source.closeCalls).toBe(0);
    expect(timer).not.toHaveBeenCalled();
  });

  it("isolates parse failures and one failing business handler", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const client = new EventStreamClient("/events");
    const source = currentSource();
    const failing = vi.fn(() => {
      throw new Error("handler failed");
    });
    const healthy = vi.fn();
    client.on("app.status", failing);
    client.on("app.status", healthy);

    source.emitMessage("app.status", "not-json");
    source.emitMessage("app.status", '{"value":9}');

    expect(failing).toHaveBeenCalledOnce();
    expect(healthy).toHaveBeenCalledOnce();
    expect(healthy).toHaveBeenCalledWith(
      { value: 9 },
      expect.any(MessageEvent)
    );
    expect(error).toHaveBeenCalledTimes(2);
  });

  it("closes before delivering Session invalidation to every registered handler", () => {
    const client = new EventStreamClient("/events");
    const source = currentSource();
    const observed: Array<{ closeCalls: number; payload: SessionInvalidatedPayload }> = [];
    client.on<SessionInvalidatedPayload>(SESSION_INVALIDATED_EVENT, (payload) => {
      observed.push({ closeCalls: source.closeCalls, payload });
    });
    client.on<SessionInvalidatedPayload>(SESSION_INVALIDATED_EVENT, (payload) => {
      observed.push({ closeCalls: source.closeCalls, payload });
    });

    source.emitMessage(
      SESSION_INVALIDATED_EVENT,
      '{"title":"Expired","message":"Sign in again","login_url":"/login"}'
    );

    expect(source.closeCalls).toBe(1);
    expect(observed).toEqual([
      {
        closeCalls: 1,
        payload: {
          login_url: "/login",
          message: "Sign in again",
          title: "Expired"
        }
      },
      {
        closeCalls: 1,
        payload: {
          login_url: "/login",
          message: "Sign in again",
          title: "Expired"
        }
      }
    ]);
  });

  it("closes idempotently and removes every native listener", () => {
    const client = new EventStreamClient("/events");
    const source = currentSource();
    const message = vi.fn();
    const open = vi.fn();
    const error = vi.fn();
    client.on("app.status", message);
    client.onOpen(open);
    client.onError(error);

    client.close();
    client.close();
    source.emitMessage("app.status", "{}");
    source.dispatchEvent(new Event("open"));
    source.dispatchEvent(new Event("error"));

    expect(source.closeCalls).toBe(1);
    expect(message).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    expect(() => client.on("app.status", vi.fn())).toThrow("closed");
  });
});

function currentSource(): FakeEventSource {
  const source = FakeEventSource.instances.at(-1);
  if (!source) throw new Error("EventStreamClient did not create an EventSource");
  return source;
}
