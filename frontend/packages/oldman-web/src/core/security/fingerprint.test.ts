import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FINGERPRINT_HEADER, createFingerprintSender, deviceVisitorId } from "./fingerprint";

const KEY = new Uint8Array(32).fill(7);

/** Decrypt the way `oldman.web.security.decryptors.AESGcmDecrypt` does, to pin the wire format. */
async function openPayload(payload: string): Promise<{ vid: string; ts: number }> {
  const raw = Uint8Array.from(atob(payload), (character) => character.charCodeAt(0));
  const key = await crypto.subtle.importKey("raw", KEY, { name: "AES-GCM" }, false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: raw.slice(0, 12) }, key, raw.slice(12));
  return JSON.parse(new TextDecoder().decode(plain));
}

describe("createFingerprintSender", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-19T00:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("produces exactly the payload the server knows how to open", async () => {
    // 服务端按 Base64(IV[12] ‖ 密文 ‖ Tag[16]) 解，明文是 {vid, ts}；对不上就静默 403。
    const sender = createFingerprintSender({ key: KEY, visitorId: () => "visitor-0001" });

    const opened = await openPayload(await sender.payload());

    expect(opened.vid).toBe("visitor-0001");
    expect(opened.ts).toBe(Date.now());
  });

  it("sends it under the header the guard reads", async () => {
    const sender = createFingerprintSender({ key: KEY, visitorId: () => "visitor-0002" });
    expect(Object.keys(await sender.headers())).toEqual([FINGERPRINT_HEADER]);
  });

  it("reuses one payload until it expires, rather than encrypting per request", async () => {
    const sender = createFingerprintSender({ key: KEY, visitorId: () => "visitor-0003", ttlMs: 60_000 });

    const first = await sender.payload();
    expect(await sender.payload()).toBe(first);

    vi.setSystemTime(Date.now() + 60_001);
    const refreshed = await sender.payload();
    expect(refreshed).not.toBe(first);
    expect((await openPayload(refreshed)).ts).toBe(Date.now());
  });

  it("gives every payload its own IV", async () => {
    // 固定 IV 会让相同明文产出相同密文，等于把"同一个访客"写在明面上。
    const sender = createFingerprintSender({ key: KEY, visitorId: () => "visitor-0004", ttlMs: 0 });
    const seen = new Set<string>();
    for (let index = 0; index < 5; index += 1) seen.add((await sender.payload()).slice(0, 16));
    expect(seen.size).toBe(5);
  });

  it("asks for the visitor id once and keeps it in memory only", async () => {
    const provider = vi.fn(() => "visitor-0005");
    const sender = createFingerprintSender({ key: KEY, visitorId: provider, ttlMs: 0 });

    await sender.payload();
    await sender.payload();
    expect(provider).toHaveBeenCalledTimes(1);

    sender.reset();
    await sender.payload();
    expect(provider).toHaveBeenCalledTimes(2);
  });

  it("derives a stable id from the device when the app supplies no provider", async () => {
    // 默认实现不落地、也不随机：随机 id 客户端想换就换，等于没有指纹。
    const first = await deviceVisitorId();
    expect(first).toMatch(/^[0-9a-f]{32}$/);
    expect(await deviceVisitorId()).toBe(first);
  });
});

describe("fingerprint caching and TTL", () => {
  it("does not cache a failed visitor id forever", async () => {
    // `identity ??= Promise.resolve(...)` 缓存的是 **Promise 本身**：自定义 visitorId
    // 提供者（文档建议换成 FingerprintJS 之类，那通常要发网络请求）一旦瞬时失败，
    // 这个 rejected promise 会被一直复用，之后每次取载荷都拿到同一个 rejection，
    // 只有显式 reset() 能恢复——而没有任何代码在失败时调它。
    let attempt = 0;
    const sender = createFingerprintSender({
      key: new Uint8Array(32),
      visitorId: async () => {
        attempt += 1;
        if (attempt === 1) throw new Error("provider offline");
        return "visitor-2";
      }
    });

    await expect(sender.visitorId()).rejects.toThrow("provider offline");
    await expect(sender.visitorId()).resolves.toBe("visitor-2");
    expect(attempt).toBe(2);
  });
});
