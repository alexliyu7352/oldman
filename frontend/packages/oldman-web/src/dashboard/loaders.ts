/**
 * Dashboard component loaders.
 */

import { createFrameworkComponentLoaders, loadSidebarMenuComponent, loadTableComponent } from "../components/loaders";
import type { DashboardComponentLoaders } from "./index";

export function createDashboardComponentLoaders(overrides: DashboardComponentLoaders = {}): DashboardComponentLoaders {
  return {
    ...createFrameworkComponentLoaders(),
    feedback: async () => (await import("./feedback")).DashboardFeedback,
    modal: async () => (await import("./modal")).DashboardModal,
    ...overrides
  };
}

/**
 * Load the shared shell navigation and server-rendered CRUD table without
 * pulling optional chart, select, date-time or upload chunks into an app.
 */
export function createDashboardCrudComponentLoaders(overrides: DashboardComponentLoaders = {}): DashboardComponentLoaders {
  return {
    "sidebar-menu": loadSidebarMenuComponent,
    table: loadTableComponent,
    ...overrides
  };
}
