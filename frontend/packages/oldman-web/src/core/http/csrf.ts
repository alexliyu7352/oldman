import { getCookie } from "./cookies";

export function isStateChangingMethod(method: string): boolean {
  return !["GET", "HEAD", "OPTIONS", "TRACE"].includes(method.toUpperCase());
}

/**
 * 读取本站的 CSRF token：先找隐藏字段，再找 meta，最后回落到 cookie。
 *
 * `scope` 默认整个文档，于是拿到的是**文档里第一个** `csrfmiddlewaretoken`。默认配置下
 * 无害：token 绑 session 不绑路径，一个页面上所有 token 相同。
 *
 * **但服务端打开 `web.security.csrf.check_url` 之后不是这样**：那时 token 绑定到请求路径
 * （`oldman/web/security/csrf/manager.py` 的 `_get_url_hash`），同一页上指向不同路径的两个
 * 表单会持有两个不同的 token，而这里对两者都返回第一个——第二个表单的请求会带错 token 被拒。
 *
 * HTTP 客户端的拦截器只拿得到 axios config，看不到是哪个表单发起的，所以它只能用默认作用域。
 * 打开 `check_url` 且一页有多个指向不同路径的表单时，请自己取 token：
 * `getCsrfToken(undefined, form)`，再把它放进请求头。
 */
export function getCsrfToken(cookieName = "csrftoken", scope: ParentNode = document): string | null {
  const input = scope.querySelector<HTMLInputElement>("input[name=csrfmiddlewaretoken]");
  if (input?.value) return input.value;

  const meta = document.querySelector<HTMLMetaElement>("meta[name=csrf-token]");
  if (meta?.content) return meta.content;

  return getCookie(cookieName);
}
