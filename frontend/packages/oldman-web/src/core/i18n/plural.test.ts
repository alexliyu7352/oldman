import { describe, expect, it } from "vitest";
import { selectPluralIndex } from "./plural";

describe("selectPluralIndex", () => {
  it("evaluates simple gettext plural expressions", () => {
    expect(selectPluralIndex("n != 1", 1)).toBe(0);
    expect(selectPluralIndex("n != 1", 2)).toBe(1);
    expect(selectPluralIndex("n > 1", 1)).toBe(0);
    expect(selectPluralIndex("n > 1", 2)).toBe(1);
  });

  it("evaluates ternary plural expressions without eval", () => {
    const rule = "n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2";

    expect(selectPluralIndex(rule, 1)).toBe(0);
    expect(selectPluralIndex(rule, 2)).toBe(1);
    expect(selectPluralIndex(rule, 5)).toBe(2);
    expect(selectPluralIndex(rule, 21)).toBe(0);
    expect(selectPluralIndex(rule, 22)).toBe(1);
    expect(selectPluralIndex(rule, 25)).toBe(2);
    expect(selectPluralIndex(rule, 111)).toBe(2);
  });

  it("falls back to English-style plurals for unsupported expressions", () => {
    expect(selectPluralIndex("window.alert(n)", 1)).toBe(0);
    expect(selectPluralIndex("window.alert(n)", 3)).toBe(1);
  });
});
