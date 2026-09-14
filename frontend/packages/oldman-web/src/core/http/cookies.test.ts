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
});
