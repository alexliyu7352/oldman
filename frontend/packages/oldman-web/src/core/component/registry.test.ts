import { describe, expect, it } from "vitest";
import { Component } from "./component";
import { ComponentRegistry } from "./registry";

class ParentComponent extends Component {
  static componentName = "panel";
}

class LocalComponent extends Component {
  static componentName = "panel";
}

class FallbackComponent extends Component {
  static componentName = "fallback";
}

describe("ComponentRegistry", () => {
  it("resolves local components before parent components and falls back to the parent", () => {
    const parent = new ComponentRegistry();
    parent.register(ParentComponent);
    parent.register(FallbackComponent);

    const local = new ComponentRegistry(parent);
    local.register(LocalComponent);

    expect(local.resolve("panel")).toBe(LocalComponent);
    expect(local.resolve("fallback")).toBe(FallbackComponent);
    expect(parent.resolve("panel")).toBe(ParentComponent);
    expect(local.resolve("missing")).toBeNull();
  });
});
