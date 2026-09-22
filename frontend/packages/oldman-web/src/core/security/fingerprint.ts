/**
 * 浏览器端指纹载荷：把 `{vid, ts}` 用 AES-GCM 加密成一个请求头。
 *
 * **这不是认证。** 密钥必须和服务端是同一把，而它跑在浏览器里——任何人打开 devtools
 * 都能拿到并自己签一份。它的作用是抬高脚本化滥用的成本：抓取方得跑完页面的加密流程、
 * 带着一个稳定的 visitor id 过限流器。谁是谁，请用会话判断。
 *
 * **密钥从哪来：构建期注入，不要从页面下发。** 框架不替应用决定这件事——每个部署的
 * 密钥不同，而框架的 bundle 是统一发布的。应用在自己的构建里把密钥喂进来，混淆强度
 * 由应用自己决定（Vite `define`、分段拼接、两段异或……）。写进 meta 标签或专门开个
 * 接口下发，等于 grep 一下就有，比不做还糟——它会让人以为有防护。
 *
 * 服务端对应 `oldman.web.security.guard.fingerprint_required`。
 */

/** 服务端读取载荷的请求头名，和 Python 侧的 FINGERPRINT_HEADER 一致。 */
export const FINGERPRINT_HEADER = "X-Oldman-Fingerprint";

/**
 * 一份加密载荷复用多久。
 *
 * **必须明显小于服务端的 `web.security.fingerprint.timestamp_max_diff`(默认 300000ms)。**
 * 两边取同一个数就没有余量:请求在载荷寿命的最后几毫秒发出、再加上网络延迟,
 * 到达时已经越过容差,拿到 403——而客户端认为载荷仍然有效,下次还是同一份,
 * 直到 TTL 真的走完。时钟漂移会把这个窗口进一步放大。表现为偶发、无法复现的 403。
 *
 * 这里留 60 秒余量。**调低服务端的 `timestamp_max_diff` 时必须同步调低 `ttlMs`**;
 * `tests/test_oldman_web_security.py` 会守住这个关系。
 */
const DEFAULT_TTL_MS = 4 * 60 * 1000;

export interface FingerprintSenderOptions {
  /** 32 字节 AES 密钥，由应用在构建期注入。 */
  key: Uint8Array;
  /** 产出 visitor id；默认用设备特征派生，应用可换成 FingerprintJS 之类。 */
  visitorId?: () => string | Promise<string>;
  /** 一份加密载荷复用多久；默认 5 分钟。 */
  ttlMs?: number;
  /** 请求头名，默认 `X-Oldman-Fingerprint`。 */
  headerName?: string;
}

export interface FingerprintSender {
  /** 当前的 visitor id（只在内存里，不落地）。 */
  visitorId(): Promise<string>;
  /** 当前有效的加密载荷，必要时重新生成。 */
  payload(): Promise<string>;
  /** 可直接展开进 fetch/axios 的请求头。 */
  headers(): Promise<Record<string, string>>;
  /** 丢掉缓存的载荷与 visitor id。 */
  reset(): void;
}

/** 设备特征派生的回落 visitor id：不引入第三方依赖，也不落地。 */
export async function deviceVisitorId(): Promise<string> {
  const nav = navigator;
  const parts = [
    nav.userAgent,
    nav.language,
    (nav.languages ?? []).join(","),
    String(screen.width),
    String(screen.height),
    String(screen.colorDepth),
    String(new Date().getTimezoneOffset()),
    String(nav.hardwareConcurrency ?? 0),
    String((nav as Navigator & { deviceMemory?: number }).deviceMemory ?? 0)
  ].join("|");

  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(parts));
  return Array.from(new Uint8Array(digest).slice(0, 16))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * 建一个发送器。
 *
 * 载荷格式和服务端的 `AESGcmDecrypt` 对齐：`Base64(IV[12] ‖ 密文 ‖ Tag[16])`，
 * 明文是 `{"vid": ..., "ts": 毫秒时间戳}`。时间戳由服务端按 `timestamp_max_diff`
 * 校验，所以载荷带 TTL 复用，过期就重算——不是每个请求都做一次 AES。
 */
export function createFingerprintSender(options: FingerprintSenderOptions): FingerprintSender {
  const ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
  const headerName = options.headerName ?? FINGERPRINT_HEADER;
  const resolveVisitorId = options.visitorId ?? deviceVisitorId;

  let cryptoKey: Promise<CryptoKey> | null = null;
  let identity: Promise<string> | null = null;
  let cached = "";
  let cachedUntil = 0;

  function importedKey(): Promise<CryptoKey> {
    // `false` 表示不可导出：拿到这个 CryptoKey 也读不出原始字节。
    // 和 visitorId 不同，这里**不**在失败时剔除缓存：导入密钥失败的原因是密钥本身
    // （长度不对、格式不对），重试一万次也是同一个结果，剔除只会把同一个错误再算一遍。
    cryptoKey ??= crypto.subtle.importKey("raw", options.key as BufferSource, { name: "AES-GCM" }, false, ["encrypt"]);
    return cryptoKey;
  }

  async function encrypt(): Promise<string> {
    const body = JSON.stringify({ vid: await visitorId(), ts: Date.now() });
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const sealed = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      await importedKey(),
      new TextEncoder().encode(body)
    );

    const combined = new Uint8Array(iv.length + sealed.byteLength);
    combined.set(iv, 0);
    combined.set(new Uint8Array(sealed), iv.length);

    let binary = "";
    for (const byte of combined) binary += String.fromCharCode(byte);
    return btoa(binary);
  }

  /**
   * 缓存 visitor id 的解析结果；**失败的那次不进缓存**。
   *
   * 缓存的是 Promise 本身，所以自定义提供者（文档建议可换成 FingerprintJS 之类，
   * 那通常要发网络请求）一旦瞬时失败，这个 rejected promise 会被一直复用，
   * 之后每次取载荷都拿到同一个 rejection，只有显式 `reset()` 能恢复——
   * 而没有任何代码会在失败时调它。
   */
  function visitorId(): Promise<string> {
    identity ??= Promise.resolve(resolveVisitorId()).catch((error: unknown) => {
      identity = null;
      throw error;
    });
    return identity;
  }

  async function payload(): Promise<string> {
    const now = Date.now();
    if (!cached || now >= cachedUntil) {
      cached = await encrypt();
      cachedUntil = now + ttlMs;
    }
    return cached;
  }

  return {
    visitorId,
    payload,
    async headers(): Promise<Record<string, string>> {
      return { [headerName]: await payload() };
    },
    reset(): void {
      identity = null;
      cached = "";
      cachedUntil = 0;
    }
  };
}
