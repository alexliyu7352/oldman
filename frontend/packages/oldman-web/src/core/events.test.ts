import { describe, expect, it, vi } from "vitest";
import { onCoreEvent } from "./events";

describe("onCoreEvent", () => {
  it("registers a typed core event listener and cleans it up", () => {
    const handler = vi.fn();
    const trigger = document.createElement("button");
    const stop = onCoreEvent(document, "om:action:success", (event) => {
      event.detail.response.message.toUpperCase();
      event.detail.method.toUpperCase();
      handler(event.detail);
    });

    document.dispatchEvent(
      new CustomEvent("om:action:success", {
        bubbles: true,
        detail: {
          method: "post",
          params: {},
          response: {
            error_code: 0,
            message: "updated",
            data: {},
            actions: []
          },
          trigger,
          url: "/updates"
        }
      })
    );

    stop();
    document.dispatchEvent(
      new CustomEvent("om:action:success", {
        bubbles: true,
        detail: {
          method: "post",
          params: {},
          response: {
            error_code: 0,
            message: "late",
            data: {},
            actions: []
          },
          trigger,
          url: "/updates"
        }
      })
    );

    expect(handler).toHaveBeenCalledOnce();
    expect(handler).toHaveBeenCalledWith({
      method: "post",
      params: {},
      response: {
        error_code: 0,
        message: "updated",
        data: {},
        actions: []
      },
      trigger,
      url: "/updates"
    });
  });

  it("types page state lifecycle details", () => {
    const handler = vi.fn();
    const stop = onCoreEvent(document, "om:page:state", (event) => {
      event.detail.state.toUpperCase();
      handler(event.detail.state);
    });

    document.dispatchEvent(
      new CustomEvent("om:page:state", {
        bubbles: true,
        detail: {
          page: {},
          previousState: "mounting",
          state: "mounted"
        }
      })
    );

    stop();
    expect(handler).toHaveBeenCalledWith("mounted");
  });

  it("types action invalid listeners with request context", () => {
    const handler = vi.fn();
    const form = document.createElement("form");
    const input = document.createElement("input");
    const trigger = document.createElement("button");
    const stop = onCoreEvent(document, "om:action:invalid", (event) => {
      event.detail.method.toUpperCase();
      event.detail.url?.toUpperCase();
      handler(event.detail.controls, event.detail.form, event.detail.trigger);
    });

    document.dispatchEvent(
      new CustomEvent("om:action:invalid", {
        bubbles: true,
        detail: {
          controls: [input],
          form,
          method: "post",
          trigger,
          url: "/updates"
        }
      })
    );

    stop();
    expect(handler).toHaveBeenCalledWith([input], form, trigger);
  });

  it("types action request listeners with request context", () => {
    const handler = vi.fn();
    const trigger = document.createElement("button");
    const stop = onCoreEvent(document, "om:action:request", (event) => {
      event.detail.method.toUpperCase();
      event.detail.params.page = "2";
      event.detail.url.toUpperCase();
      handler(event.detail.trigger, event.detail.params);
    });

    document.dispatchEvent(
      new CustomEvent("om:action:request", {
        bubbles: true,
        detail: {
          method: "post",
          params: {},
          trigger,
          url: "/updates"
        }
      })
    );

    stop();
    expect(handler).toHaveBeenCalledWith(trigger, { page: "2" });
  });
});
