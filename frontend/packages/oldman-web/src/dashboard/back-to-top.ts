import { BackToTop, type BackToTopOptions } from "../components/back-to-top";
import { Component, type ComponentOptions } from "../core/index";

export interface DashboardBackToTopOptions extends ComponentOptions {
  buttonOptions?: BackToTopOptions;
  buttonSelector?: string;
}

const DEFAULT_BUTTON_SELECTOR = "#back-to-top";

export class DashboardBackToTop extends Component {
  private readonly buttonOptions: BackToTopOptions;
  private readonly buttonSelector: string;

  constructor(root: HTMLElement, options: DashboardBackToTopOptions = {}) {
    super(root, options);
    this.buttonOptions = options.buttonOptions ?? {};
    this.buttonSelector = options.buttonSelector ?? DEFAULT_BUTTON_SELECTOR;
  }

  override async mount(): Promise<void> {
    const button = this.root.querySelector<HTMLElement>(this.buttonSelector);
    if (!button) return;

    const component = new DashboardBackToTopButton(button, {
      ...this.buttonOptions,
      page: this.page,
      i18n: this.i18n
    });
    await component.start();
    this.cleanupRegistry.add(() => component.stop());
  }
}

class DashboardBackToTopButton extends BackToTop {
  protected override setVisible(visible: boolean): void {
    super.setVisible(visible);
    this.root.style.display = visible ? "block" : "none";
  }
}
