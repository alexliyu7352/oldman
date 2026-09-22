import { beforeEach, describe, expect, it } from "vitest";
import { deleteCookie, getCookie, serializeCookie, setCookie } from "./cookies";

describe("cookies", () => {
  beforeEach(() => {
    for (const cookie of document.cookie.split(";")) {
      const name = cookie.split("=")[0]?.trim();
      if (name) document.cookie = `${name}=; Max-Age=0; Path=/`;
    }
  });

  it("reads decoded cookie values by name", () => {
    document.cookie = "session=abc%20123; Path=/";
    document.cookie = "theme=dark; Path=/";

    expect(getCookie("session")).toBe("abc 123");
    expect(getCookie("missing")).toBeNull();
  });

  it("sets and deletes browser cookies", () => {
    setCookie("locale", "zh-CN", { path: "/" });

    expect(getCookie("locale")).toBe("zh-CN");

    deleteCookie("locale", { path: "/" });

    expect(getCookie("locale")).toBeNull();
  });

  it("serializes cookie attributes", () => {
    expect(
      serializeCookie("prefs", "a b", {
        domain: "example.com",
        maxAge: 3600,
        path: "/admin",
        sameSite: "Lax",
        secure: true
      })
    ).toBe("prefs=a%20b; Max-Age=3600; Domain=example.com; Path=/admin; Secure; SameSite=Lax");
  });

  it("SameSite=None 自动补 Secure，否则浏览器会静默丢弃这条 cookie", () => {
    // 规范要求 SameSite=None 必须同时带 Secure；缺了它，浏览器直接拒收这条 cookie，
    // 而且不报错。代码、lint、类型检查都看不出来，只有跨站场景在运行时莫名失效。
    // 这不是框架替使用者做决定:没有 Secure 的 SameSite=None 本来就没有一种能生效的用法。
    expect(serializeCookie("a", "1", { sameSite: "None" })).toContain("Secure");
    expect(serializeCookie("a", "1", { sameSite: "None", secure: true })).toContain("Secure");
  });

  it("其余 SameSite 取值不会被强加 Secure", () => {
    expect(serializeCookie("a", "1", { sameSite: "Lax" })).not.toContain("Secure");
    expect(serializeCookie("a", "1", { sameSite: "Strict" })).not.toContain("Secure");
    expect(serializeCookie("a", "1", {})).not.toContain("Secure");
  });
});
