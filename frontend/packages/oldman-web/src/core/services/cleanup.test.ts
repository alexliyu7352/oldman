import { describe, expect, it, vi } from "vitest";
import { CleanupRegistry } from "./cleanup";

describe("CleanupRegistry", () => {
  it("runs callbacks once in reverse registration order", async () => {
    const registry = new CleanupRegistry();
    const calls: string[] = [];

    registry.add(() => {
      calls.push("first");
    });
    registry.add(() => {
      calls.push("second");
    });

    await registry.run();
    await registry.run();

    expect(calls).toEqual(["second", "first"]);
  });

  it("continues cleanup if one callback throws", async () => {
    const registry = new CleanupRegistry();
    const logger = { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() };
    const calls: string[] = [];

    registry.add(() => {
      calls.push("safe");
    });
    registry.add(() => {
      throw new Error("cleanup failed");
    });

    await registry.run(logger);

    expect(calls).toEqual(["safe"]);
    expect(logger.error).toHaveBeenCalledOnce();
  });

  it("reports async cleanup rejections and continues later callbacks", async () => {
    const registry = new CleanupRegistry();
    const logger = { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() };
    const calls: string[] = [];
    const error = new Error("async cleanup failed");

    registry.add(() => {
      calls.push("first");
    });
    registry.add(async () => {
      calls.push("second");
      throw error;
    });
    registry.add(() => {
      calls.push("third");
    });

    await registry.run(logger);

    expect(calls).toEqual(["third", "second", "first"]);
    expect(logger.error).toHaveBeenCalledWith("[oldman] cleanup callback failed", error);
  });
});
