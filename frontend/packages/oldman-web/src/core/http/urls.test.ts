import { describe, expect, it } from "vitest";

import { isSameOriginRequest, isSameSitePath } from "./urls";

describe("isSameSitePath", () => {
  it("accepts a plain local path and refuses anything that leaves the site", () => {
    expect(isSameSitePath("/admin/users")).toBe(true);
    expect(isSameSitePath("//evil.test/x")).toBe(false);
    expect(isSameSitePath("https://evil.test")).toBe(false);
    expect(isSameSitePath("/a\\b")).toBe(false);
  });
});
describe("isSameOriginRequest", () => {
  it("treats a relative url as same origin", () => {
    expect(isSameOriginRequest("/admin/users")).toBe(true);
    expect(isSameOriginRequest(undefined)).toBe(true);
  });

  it("refuses an absolute url pointing somewhere else", () => {
    // The CSRF token is this site's secret; it must not travel to a foreign origin.
    expect(isSameOriginRequest("https://attacker.test/collect")).toBe(false);
  });

  it("accepts an absolute url that resolves back to this origin", () => {
    expect(isSameOriginRequest(`${window.location.origin}/admin/users`)).toBe(true);
  });

  it("resolves against an explicit base url", () => {
    expect(isSameOriginRequest("/x", "https://attacker.test")).toBe(false);
    expect(isSameOriginRequest("/x", window.location.origin)).toBe(true);
  });

  it("refuses anything it cannot parse", () => {
    expect(isSameOriginRequest("http://[", undefined)).toBe(false);
  });
});
