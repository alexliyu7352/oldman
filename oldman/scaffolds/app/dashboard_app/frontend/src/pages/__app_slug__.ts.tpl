import { setupPage } from "oldman-web/core";
import { createDashboardComponentLoaders, DashboardPage } from "oldman-web/dashboard";

class {{ app_class }}Page extends DashboardPage {
  constructor(root: HTMLElement) {
    super({
      componentLoaders: createDashboardComponentLoaders(),
      root
    });
  }
}

setupPage("{{ app_slug }}", {{ app_class }}Page);
