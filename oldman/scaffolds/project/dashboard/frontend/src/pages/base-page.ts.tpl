import { createDashboardComponentLoaders, DashboardPage } from "oldman-web/dashboard";

/**
 * The page every dashboard page of this project builds on: sidebar, topbar and the framework's components,
 * each loaded the first time a page uses it. A page with its own loaders or actions extends it.
 */
export class BasePage extends DashboardPage {
  constructor(root: HTMLElement) {
    super({
      componentLoaders: createDashboardComponentLoaders(),
      root
    });
  }
}
