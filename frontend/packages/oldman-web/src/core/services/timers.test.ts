import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CleanupRegistry } from "./cleanup";
import { TimerService } from "./timers";

describe("TimerService", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("clears intervals through cleanup registry", async () => {
    const cleanup = new CleanupRegistry();
    const timers = new TimerService(cleanup);
    const callback = vi.fn();

    timers.interval(callback, 1000);
    vi.advanceTimersByTime(1000);
    await cleanup.run();
    vi.advanceTimersByTime(3000);

    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("clears timeouts through cleanup registry", async () => {
    const cleanup = new CleanupRegistry();
    const timers = new TimerService(cleanup);
    const callback = vi.fn();

    timers.timeout(callback, 1000);
    await cleanup.run();
    vi.advanceTimersByTime(1000);

    expect(callback).not.toHaveBeenCalled();
  });
});
