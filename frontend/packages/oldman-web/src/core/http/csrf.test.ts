import { afterEach, describe, expect, it } from "vitest";
import { getCsrfToken, isStateChangingMethod } from "./csrf";

describe("csrf", () => {
  afterEach(() => {
    document.body.replaceChildren();
    document.head.replaceChildren();
    for (const cookie of document.cookie.split(";")) {
      const name = cookie.split("=")[0]?.trim();
      if (name) document.cookie = `${name}=; Max-Age=0; Path=/`;
    }
  });

  it("reads token from hidden form field before meta and cookie", () => {
    document.body.innerHTML = `<input type="hidden" name="csrfmiddlewaretoken" value="hidden-token">`;
    document.head.innerHTML = `<meta name="csrf-token" content="meta-token">`;
    document.cookie = "csrftoken=cookie-token; Path=/";

    expect(getCsrfToken()).toBe("hidden-token");
  });

  it("reads token from meta", () => {
    document.head.innerHTML = `<meta name="csrf-token" content="abc">`;
    expect(getCsrfToken()).toBe("abc");
  });

  it("falls back to csrftoken cookie", () => {
    document.cookie = "csrftoken=cookie-token; Path=/";

    expect(getCsrfToken()).toBe("cookie-token");
  });

  it("detects state changing methods", () => {
    expect(isStateChangingMethod("post")).toBe(true);
    expect(isStateChangingMethod("GET")).toBe(false);
  });

  it("可以把查找范围限定到一个表单，供 check_url 打开时自取 token", () => {
    // 默认取文档里第一个;`check_url` 打开后 token 绑路径,同页两个指向不同路径的表单
    // 会有两个不同 token,那时调用方需要自己按表单取。
    document.body.innerHTML = `
      <form id="first"><input type="hidden" name="csrfmiddlewaretoken" value="token-first"></form>
      <form id="second"><input type="hidden" name="csrfmiddlewaretoken" value="token-second"></form>
    `;
    const second = document.querySelector<HTMLFormElement>("#second")!;

    expect(getCsrfToken()).toBe("token-first");
    expect(getCsrfToken(undefined, second)).toBe("token-second");
  });
});
