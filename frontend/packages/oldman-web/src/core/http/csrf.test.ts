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
});
