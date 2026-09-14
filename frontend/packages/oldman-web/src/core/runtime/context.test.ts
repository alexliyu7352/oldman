import { describe, expect, it, vi } from "vitest";
import type { HttpClient } from "../http/client";
import { createOldmanContext, getOldmanContext, resetOldmanContext, setOldmanContext } from "./context";

describe("Oldman runtime context", () => {
  it("returns one singleton context until reset", () => {
    resetOldmanContext();

    const first = getOldmanContext();
    const second = getOldmanContext();
    expect(second).toBe(first);

    resetOldmanContext();
    expect(getOldmanContext()).not.toBe(first);
  });

  it("resolves static asset urls from the configured asset base", () => {
    const context = createOldmanContext({ assetBaseUrl: "http://localhost:5173/" });
    setOldmanContext(context);

    expect(getOldmanContext().assetUrl("i18n/zh-hans.json")).toBe("http://localhost:5173/i18n/zh-hans.json");
  });

  it("keeps shared http separate from scoped http clients", () => {
    const sharedHttp = { shared: true } as unknown as HttpClient;
    const scopedHttp = { scoped: true } as unknown as HttpClient;
    const signal = new AbortController().signal;
    const httpFactory = vi.fn(() => scopedHttp);

    const context = createOldmanContext({ http: sharedHttp, httpFactory });

    expect(context.http).toBe(sharedHttp);
    expect(context.createHttpClient({ signal })).toBe(scopedHttp);
    expect(httpFactory).toHaveBeenCalledWith({ onAuthRedirect: expect.any(Function), signal });
  });

  it("injects the default auth redirect handler into created http clients", () => {
    const scopedHttp = { scoped: true } as unknown as HttpClient;
    const httpFactory = vi.fn(() => scopedHttp);

    const context = createOldmanContext({ httpFactory });
    context.createHttpClient({ timeout: 1000 });

    expect(httpFactory).toHaveBeenLastCalledWith({
      onAuthRedirect: expect.any(Function),
      timeout: 1000
    });
  });
});
