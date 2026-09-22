import { Component, getOldmanContext, type LanguageChangeDetail } from "../core/index";

/** Keep every dashboard consumer on the same language-switching behavior. */
export class LanguageSwitcher extends Component {
  private selectionSequence = 0;

  override async mount(): Promise<void> {
    this.syncLanguageState(this.i18n.currentLanguage);

    this.on("click", "[data-lang]", (event, trigger) => {
      event.preventDefault();
      const language = trigger.getAttribute("data-lang");
      if (!language) return;
      const sequence = ++this.selectionSequence;
      const previousLanguage = this.i18n.currentLanguage;
      void this.i18n.setLanguage(language, { syncBackend: this.shouldSyncBackend(trigger) }).then((resolvedLanguage) => {
        if (sequence !== this.selectionSequence) return;
        this.syncLanguageState(resolvedLanguage);
        this.closeContainingDropdown();
        const targetUrl = trigger.getAttribute("data-om-language-url");
        if (resolvedLanguage !== previousLanguage && targetUrl) {
          window.location.assign(targetUrl);
        }
      });
    });

    this.listen<CustomEvent<LanguageChangeDetail>>(document, "om:i18n:change", (event) => {
      this.syncLanguageState(event.detail.language);
    });
  }

  private syncLanguageState(language: string): void {
    const context = getOldmanContext();
    const normalized = this.i18n.resolveLanguageCode(language);
    const definition = this.i18n.getLanguageDefinition(normalized);
    const flagUrl = definition.flagUrl === undefined
      ? (definition.flag ? context.assetUrl(definition.flag) : "")
      : definition.flagUrl;

    for (const flag of this.$$<HTMLImageElement>("[data-om-language-current-flag]")) {
      if (flagUrl) {
        flag.src = flagUrl;
        flag.hidden = false;
      } else {
        flag.removeAttribute("src");
        flag.hidden = true;
      }
      flag.alt = definition.name;
    }

    // The trigger always shows the language name; a flag image, when present, is decoration.
    for (const name of this.$$<HTMLElement>("[data-om-language-current-name]")) {
      name.textContent = definition.name;
      name.hidden = false;
    }

    for (const button of this.$$<HTMLElement>("[data-om-language-current]")) {
      button.classList.toggle("has-language-name", !flagUrl);
    }

    for (const option of this.$$<HTMLElement>("[data-lang]")) {
      const active = this.i18n.resolveLanguageCode(option.getAttribute("data-lang")) === normalized;
      option.classList.toggle("active", active);
      option.setAttribute("aria-pressed", active ? "true" : "false");
    }
  }

  private shouldSyncBackend(trigger: Element): boolean {
    return this.root.dataset.omLanguageSync !== "false" && trigger.getAttribute("data-om-language-sync") !== "false";
  }

  /** Close only the dropdown that owns this switcher after a successful choice. */
  private closeContainingDropdown(): void {
    const dropdown = this.root.closest<HTMLElement>('[data-om-component~="dropdown"], .om-dropdown');
    const toggle = dropdown?.querySelector<HTMLElement>("[data-om-dropdown-toggle]");
    const menu = dropdown?.querySelector<HTMLElement>("[data-om-dropdown-menu], .om-dropdown-menu");
    if (!toggle || !menu) return;
    if (toggle.getAttribute("aria-expanded") === "true" || menu.classList.contains("show") || !menu.hidden) {
      toggle.click();
    }
  }
}
