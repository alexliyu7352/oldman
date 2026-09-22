/** URL helpers shared by every component that reads one out of the DOM or builds one. */

const CONTROL_CHARACTERS = /[\x00-\x1f\x7f]/;

/**
 * 判断一个值是否是可以安全跟随的同站路径。
 *
 * 这些路径来自 `data-om-*` 属性，也就是服务端渲染进 HTML 的地方；拒绝协议相对
 * ("//host")、反斜杠和控制字符，避免把请求引到站外或绕过路径校验。
 */
export function isSameSitePath(value: unknown): value is string {
  return typeof value === "string"
    && value.startsWith("/")
    && !value.startsWith("//")
    && !value.includes("\\")
    && !CONTROL_CHARACTERS.test(value);
}

/** 同源地址收敛成相对路径，跨源保持原样，这样请求不会带上多余的 origin。 */
export function relativeUrl(url: URL): string {
  if (url.origin !== window.location.origin) return url.toString();
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * 判断一次请求最终会不会落在本站。
 *
 * CSRF token 是本站的秘密，只能跟着发往本站的请求走。拦截器原先不看地址就附加它，
 * 于是一个绝对 URL 就能把 token 连同凭据一起送给第三方。解析不了的地址按跨站处理：
 * 拿不准时不发比发错地方安全。
 */
export function isSameOriginRequest(url: string | undefined | null, baseUrl?: string | null): boolean {
  if (!url) return true;
  try {
    const base = baseUrl ? new URL(baseUrl, window.location.href) : window.location.href;
    return new URL(url, base).origin === window.location.origin;
  } catch {
    return false;
  }
}

/**
 * 只拒绝"点一下就执行代码"的伪协议。
 *
 * 和服务端 `oldman.utils.http.is_safe_link` 是同一条规则,两边必须保持一致:
 * 服务端负责它自己发出的链接,这里负责模板属性里读到的、要交给 `location.assign` 的地址。
 * 转义只能挡住值跳出引号,挡不住 `href="javascript:…"` —— 那是脚本,不是地址。
 *
 * 允许 http/https/mailto 和相对路径:跳转到外部支付页、工单系统是正常业务需求,
 * 框架不该替使用者禁掉它。同时拒绝反斜杠和控制字符(`java\tscript:` 这类混过解析器的写法)。
 */
export function isSafeLink(value: unknown): value is string {
  if (typeof value !== "string") return false;
  for (const character of value) {
    const code = character.codePointAt(0)!;
    if (character === "\\" || code < 0x20 || code === 0x7f) return false;
  }
  // 手动取 scheme 而不是用 new URL():后者会把相对路径按当前页面补成 http,
  // 也会对一些输入抛错。这个形状和 Python 的 urlparse 一致——冒号前出现 / ? # 就不算 scheme。
  const scheme = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(value)?.[1];
  return scheme === undefined || !DANGEROUS_SCHEMES.has(scheme.toLowerCase());
}

const DANGEROUS_SCHEMES = new Set(["javascript", "data", "vbscript", "file", "blob"]);
