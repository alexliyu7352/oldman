import { describe, expect, it } from "vitest";
import { createPreferenceStore } from "../core/services/preferences";
import {
  DASHBOARD_THEME_PREFERENCE_KEY,
  readStoredDashboardTheme,
  resolveInitialDashboardTheme,
  storeDashboardTheme
} from "./theme";

const prefersDark = () => ({ matches: true });
const prefersLight = () => ({ matches: false });

describe("dashboard theme preference", () => {
  it("prefers the stored choice over the OS scheme and the template default", () => {
    const store = createPreferenceStore({ backend: "memory" });
    storeDashboardTheme(store, "dark");

    expect(readStoredDashboardTheme(store)).toBe("dark");
    expect(resolveInitialDashboardTheme(store, "light", prefersLight)).toBe("dark");
  });

  it("falls back to the OS scheme, then the template default", () => {
    const store = createPreferenceStore({ backend: "memory" });

    expect(resolveInitialDashboardTheme(store, "light", prefersDark)).toBe("dark");
    expect(resolveInitialDashboardTheme(store, "light", prefersLight)).toBe("light");
    expect(resolveInitialDashboardTheme(store, "dark", prefersLight)).toBe("dark");
    expect(resolveInitialDashboardTheme(store, "unknown", undefined)).toBe("light");
  });

  it("ignores corrupt stored values", () => {
    const store = createPreferenceStore({ backend: "memory" });
    store.set(DASHBOARD_THEME_PREFERENCE_KEY, "blue");

    expect(readStoredDashboardTheme(store)).toBeNull();
    expect(resolveInitialDashboardTheme(store, "light", prefersLight)).toBe("light");
  });
});
