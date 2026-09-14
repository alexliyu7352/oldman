import { Component } from "../core/component/component";

const TAB_SELECTOR = "[data-om-tab]";

/** 为语义化 tablist 补齐选择状态和键盘导航。 */
export class Tabs extends Component {
  static readonly componentName = "tabs";

  override async mount(): Promise<void> {
    this.on("click", TAB_SELECTOR, (event, element) => {
      const tab = element as HTMLButtonElement;
      if (!this.isOwnedTab(tab) || this.isDisabled(tab)) return;
      event.preventDefault();
      this.select(tab);
    });

    this.on("keydown", TAB_SELECTOR, (event, element) => {
      const tab = element as HTMLButtonElement;
      if (!this.isOwnedTab(tab)) return;

      const tabs = this.enabledTabs();
      const index = tabs.indexOf(tab);
      if (index < 0) return;

      let next: HTMLButtonElement | undefined;
      if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
      if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
      if (event.key === "Home") next = tabs[0];
      if (event.key === "End") next = tabs.at(-1);
      if (!next) return;

      event.preventDefault();
      this.select(next);
      next.focus();
    });

    const initial = this.tabs().find((tab) => tab.getAttribute("aria-selected") === "true" && !this.isDisabled(tab));
    const first = initial ?? this.enabledTabs()[0];
    if (first) this.select(first);
  }

  /** 激活一个 Tab，并同步对应 tabpanel 的可见状态。 */
  private select(selected: HTMLButtonElement): void {
    for (const tab of this.tabs()) {
      const active = tab === selected;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;

      const panelId = tab.getAttribute("aria-controls");
      if (!panelId) continue;
      const panel = document.getElementById(panelId);
      if (panel && this.root.contains(panel)) panel.hidden = !active;
    }
  }

  private tabs(): HTMLButtonElement[] {
    return Array.from(this.root.querySelectorAll<HTMLButtonElement>(TAB_SELECTOR)).filter((tab) => this.isOwnedTab(tab));
  }

  private enabledTabs(): HTMLButtonElement[] {
    return this.tabs().filter((tab) => !this.isDisabled(tab));
  }

  private isOwnedTab(tab: HTMLButtonElement): boolean {
    return tab.closest<HTMLElement>("[data-om-component~='tabs']") === this.root;
  }

  private isDisabled(tab: HTMLButtonElement): boolean {
    return tab.disabled || tab.getAttribute("aria-disabled") === "true";
  }
}
