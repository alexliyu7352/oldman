export type CookieSameSite = "Strict" | "Lax" | "None";

export interface CookieOptions {
  domain?: string;
  expires?: Date;
  maxAge?: number;
  path?: string;
  sameSite?: CookieSameSite;
  secure?: boolean;
}

export function getCookie(name: string): string | null {
  const encodedName = `${encodeURIComponent(name)}=`;
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(encodedName));

  return cookie ? decodeURIComponent(cookie.slice(encodedName.length)) : null;
}

export function setCookie(name: string, value: string, options: CookieOptions = {}): void {
  document.cookie = serializeCookie(name, value, options);
}

export function deleteCookie(name: string, options: Pick<CookieOptions, "domain" | "path"> = {}): void {
  setCookie(name, "", {
    ...options,
    maxAge: 0
  });
}

export function serializeCookie(name: string, value: string, options: CookieOptions = {}): string {
  const parts = [`${encodeURIComponent(name)}=${encodeURIComponent(value)}`];

  if (options.maxAge !== undefined) parts.push(`Max-Age=${options.maxAge}`);
  if (options.domain) parts.push(`Domain=${options.domain}`);
  if (options.path) parts.push(`Path=${options.path}`);
  if (options.expires) parts.push(`Expires=${options.expires.toUTCString()}`);
  // `SameSite=None` 缺了 `Secure`，浏览器会**静默丢弃**整条 cookie：不报错、不警告，
  // 代码和类型检查都看不出来，只有跨站场景在运行时莫名失效。这不是替使用者做决定——
  // 没有 `Secure` 的 `SameSite=None` 本来就没有一种能生效的用法。
  if (options.secure || options.sameSite === "None") parts.push("Secure");
  if (options.sameSite) parts.push(`SameSite=${options.sameSite}`);

  return parts.join("; ");
}
