import { BasePage } from "../app/index";

/**
 * The pages on the standalone auth base (login, password reset): a form, the language switcher and
 * its dropdown, no dashboard shell. Components load on first use, so the dashboard bundle stays lean.
 */
export class AuthPage extends BasePage {
  constructor(root: HTMLElement) {
    super({
      root,
      componentLoaders: {
        dropdown: async () => (await import("../components/dropdown")).Dropdown,
        form: async () => (await import("../components/form")).Form,
        "language-switcher": async () => (await import("../components/language-switcher")).LanguageSwitcher,
        preloader: async () => (await import("../components/preloader")).Preloader
      }
    });
  }
}
