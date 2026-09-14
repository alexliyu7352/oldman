import { afterEach, describe, expect, it, vi } from "vitest";
import { Countdown } from "./countdown";

describe("Countdown", () => {
  afterEach(() => {
    vi.useRealTimers();
    document.body.replaceChildren();
  });

  it("renders remaining parts, completes once, and clears its interval on stop", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-03T12:00:00.000Z"));
    document.body.innerHTML = `
      <div data-om-countdown-target="2026-09-03T12:00:01.500Z">
        <span data-om-countdown-days></span><span data-om-countdown-hours></span>
        <span data-om-countdown-minutes></span><span data-om-countdown-seconds></span>
        <p data-om-countdown-complete hidden>Complete</p>
      </div>
    `;
    const root = document.body.firstElementChild as HTMLElement;
    const completed = vi.fn();
    root.addEventListener("om:countdown:complete", completed);
    const component = new Countdown(root);

    await component.start();
    expect(root.querySelector("[data-om-countdown-seconds]")?.textContent).toBe("02");

    vi.advanceTimersByTime(2000);

    expect(root.dataset.omCountdownState).toBe("complete");
    expect(root.querySelector<HTMLElement>("[data-om-countdown-complete]")?.hidden).toBe(false);
    expect(completed).toHaveBeenCalledOnce();

    await component.stop();
    vi.advanceTimersByTime(2000);
    expect(completed).toHaveBeenCalledOnce();
  });
});
