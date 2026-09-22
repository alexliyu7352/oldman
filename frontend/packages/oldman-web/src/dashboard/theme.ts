import type { PreferenceStore } from "../core/services/preferences";

export type DashboardTheme = "light" | "dark";

/**
 * Preference key for the Dashboard colour theme. The template pre-paint script in
 * `oldman/dashboard/partials/theme_boot.html` reads the same key (with the default
 * `oldman:` namespace) before the bundle loads, so both must stay in sync.
 */
export const DASHBOARD_THEME_PREFERENCE_KEY = "dashboard.theme";
export const DARK_SCHEME_MEDIA_QUERY = "(prefers-color-scheme: dark)";

export function isDashboardTheme(value: unknown): value is DashboardTheme {
  return value === "light" || value === "dark";
}

export function readStoredDashboardTheme(preferences: PreferenceStore): DashboardTheme | null {
  const stored = preferences.get(DASHBOARD_THEME_PREFERENCE_KEY);
  return isDashboardTheme(stored) ? stored : null;
}

export function storeDashboardTheme(preferences: PreferenceStore, theme: DashboardTheme): void {
  preferences.set(DASHBOARD_THEME_PREFERENCE_KEY, theme);
}

/**
 * Resolve the theme for a freshly loaded document: an explicit user choice wins,
 * then the operating-system preference, then the template default.
 */
export function resolveInitialDashboardTheme(
  preferences: PreferenceStore,
  fallback: string | null | undefined,
  matchMedia: ((query: string) => { matches: boolean }) | undefined = globalThis.matchMedia?.bind(globalThis)
): DashboardTheme {
  const stored = readStoredDashboardTheme(preferences);
  if (stored) return stored;
  if (matchMedia?.(DARK_SCHEME_MEDIA_QUERY).matches) return "dark";
  return isDashboardTheme(fallback) ? fallback : "light";
}
