import { afterEach, describe, expect, it, vi } from "vitest";
import { HistoryBack } from "./history-back";

class TestHistoryBack extends HistoryBack {
  readonly navigations: string[] = [];

  protected override navigateToFallback(url: string): void {
    this.navigations.push(url);
  }
}

describe("HistoryBack", () => {
  afterEach(() => {
    document.body.replaceChildren();
    history.replaceState(null, "", "/");
    vi.restoreAllMocks();
  });

  it("uses Turbo history before fallback by default", async () => {
    document.body.innerHTML = `<a href="/records" data-om-history-back data-om-history-fallback="/records">Cancel</a>`;
    history.replaceState({ turbo: { restorationIndex: 2 } }, "", "/records/1/edit");
    const back = vi.spyOn(history, "back").mockImplementation(() => {});
    const component = new TestHistoryBack(document.body);

    await component.start();
    document.querySelector<HTMLAnchorElement>("[data-om-history-back]")!.click();

    expect(back).toHaveBeenCalledTimes(1);
    expect(component.navigations).toEqual([]);

    await component.stop();
  });

  it("uses fallback when no restorable Turbo history exists", async () => {
    document.body.innerHTML = `<a href="/records" data-om-history-back data-om-history-fallback="/records">Cancel</a>`;
    history.replaceState({ turbo: { restorationIndex: 0 } }, "", "/records/1/edit");
    const back = vi.spyOn(history, "back").mockImplementation(() => {});
    const component = new TestHistoryBack(document.body);

    await component.start();
    document.querySelector<HTMLAnchorElement>("[data-om-history-back]")!.click();

    expect(back).not.toHaveBeenCalled();
    expect(component.navigations).toEqual(["/records"]);

    await component.stop();
  });

  it("only prevents the default navigation when neither history nor fallback exists", async () => {
    document.body.innerHTML = `<a href="/records" data-om-history-back>Cancel</a>`;
    history.replaceState(null, "", "/records/1/edit");
    const back = vi.spyOn(history, "back").mockImplementation(() => {});
    const component = new TestHistoryBack(document.body);
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });

    await component.start();
    const allowed = document.querySelector<HTMLAnchorElement>("[data-om-history-back]")!.dispatchEvent(click);

    expect(allowed).toBe(false);
    expect(click.defaultPrevented).toBe(true);
    expect(back).not.toHaveBeenCalled();
    expect(component.navigations).toEqual([]);

    await component.stop();
  });
});
