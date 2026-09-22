import { afterEach, describe, expect, it, vi } from "vitest";
import { goBackOrFallback, startHistoryBack } from "./history-back";

describe("startHistoryBack", () => {
  const stops: Array<() => void> = [];

  afterEach(() => {
    while (stops.length) stops.pop()?.();
    document.body.replaceChildren();
    history.replaceState(null, "", "/");
    vi.restoreAllMocks();
  });

  function start(): void {
    stops.push(startHistoryBack(document));
  }

  it("goes back for a Cancel clicked before its page finished mounting", () => {
    document.body.innerHTML = `<a href="/records" data-om-history-back data-om-history-fallback="/records">Cancel</a>`;
    history.replaceState({ turbo: { restorationIndex: 2 } }, "", "/records/1/edit");
    const back = vi.spyOn(history, "back").mockImplementation(() => {});
    start();

    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.querySelector<HTMLAnchorElement>("[data-om-history-back]")!.dispatchEvent(click);

    // Turbo 只在 defaultPrevented 为假时接管链接，阻止默认行为就等于挡下了那次跳转。
    expect(click.defaultPrevented).toBe(true);
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("leaves the click to the mounted component that already handled it", () => {
    document.body.innerHTML = `<a href="/records" data-om-history-back data-om-history-fallback="/records">Cancel</a>`;
    history.replaceState({ turbo: { restorationIndex: 2 } }, "", "/records/1/edit");
    const back = vi.spyOn(history, "back").mockImplementation(() => {});
    document.body.addEventListener("click", (event) => event.preventDefault(), { once: true });
    start();

    document.querySelector<HTMLAnchorElement>("[data-om-history-back]")!.click();

    expect(back).not.toHaveBeenCalled();
  });

  it("ignores clicks that the browser itself treats as a new context", () => {
    document.body.innerHTML = `<a href="/records" data-om-history-back data-om-history-fallback="/records">Cancel</a>`;
    history.replaceState({ turbo: { restorationIndex: 2 } }, "", "/records/1/edit");
    const back = vi.spyOn(history, "back").mockImplementation(() => {});
    start();

    const click = new MouseEvent("click", { bubbles: true, cancelable: true, metaKey: true });
    document.querySelector<HTMLAnchorElement>("[data-om-history-back]")!.dispatchEvent(click);

    expect(click.defaultPrevented).toBe(false);
    expect(back).not.toHaveBeenCalled();
  });

  it("stops listening once the runtime is torn down", () => {
    document.body.innerHTML = `<a href="/records" data-om-history-back data-om-history-fallback="/records">Cancel</a>`;
    history.replaceState({ turbo: { restorationIndex: 2 } }, "", "/records/1/edit");
    const back = vi.spyOn(history, "back").mockImplementation(() => {});
    startHistoryBack(document)();

    document.querySelector<HTMLAnchorElement>("[data-om-history-back]")!.click();

    expect(back).not.toHaveBeenCalled();
  });
});

describe("goBackOrFallback", () => {
  afterEach(() => {
    document.body.replaceChildren();
    history.replaceState(null, "", "/");
    vi.restoreAllMocks();
  });

  function fallbackTrigger(url: string): HTMLElement {
    document.body.innerHTML = `<a data-om-history-back data-om-history-fallback="${url}">Cancel</a>`;
    // No Turbo restoration index, so the declared fallback is the only route out.
    history.replaceState(null, "", "/records/1/edit");
    return document.querySelector<HTMLElement>("[data-om-history-back]")!;
  }

  it("follows an ordinary fallback, local or external", () => {
    for (const url of ["/records", "https://vendor.example/records"]) {
      const navigate = vi.fn();
      goBackOrFallback(fallbackTrigger(url), navigate);
      expect(navigate).toHaveBeenCalledWith(url);
    }
  });

  it("refuses a fallback whose scheme executes", () => {
    // The caller hands this to window.location.assign, which runs a javascript: URL.
    for (const url of ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,&lt;script&gt;1&lt;/script&gt;"]) {
      const navigate = vi.fn();
      goBackOrFallback(fallbackTrigger(url), navigate);
      expect(navigate).not.toHaveBeenCalled();
    }
  });
});
