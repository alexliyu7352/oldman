import { Component } from "../core/component/component";
import { FormValidator, type FormValidatorInvalidDetail } from "./form-validator";

const PANEL_SELECTOR = "[data-om-step-panel]";
const INDICATOR_SELECTOR = "[data-om-step-indicator]";

/** 在一张普通 Form 内切换字段分组，只有最后一步会提交。 */
export class MultiStepForm extends Component {
  static readonly componentName = "multi-step-form";
  private currentIndex = 0;
  private form: HTMLFormElement | null = null;

  override async mount(): Promise<void> {
    this.form = this.root.closest("form");
    if (!this.form || this.panels().length === 0) throw new Error("MultiStepForm requires step panels inside a form");

    this.on("click", "[data-om-step-next]", (event) => {
      event.preventDefault();
      this.next();
    });
    this.on("click", "[data-om-step-previous]", (event) => {
      event.preventDefault();
      this.showStep(this.currentIndex - 1);
    });
    this.listen(this.form, "reset", () => queueMicrotask(() => this.showStep(0)));
    this.listen<CustomEvent<FormValidatorInvalidDetail>>(this.form, "om:form-validator:invalid", (event) => {
      this.showFirstInvalidStep(event.detail.controls);
    });
    this.listen(this.form, "om:form:error", () => this.showFirstInvalidStep());

    const firstError = this.panels().findIndex((panel) => panel.querySelector("[aria-invalid='true']"));
    this.showStep(firstError >= 0 ? firstError : 0);
  }

  override async unmount(): Promise<void> {
    this.form = null;
  }

  private next(): void {
    const panel = this.panels()[this.currentIndex];
    if (!panel) return;

    const validator = this.validator();
    const valid = validator ? validator.validateScope(panel) : this.validateNativeControls(panel);
    if (!valid) {
      this.indicators()[this.currentIndex]?.classList.add("is-error");
      this.firstInvalidControl(panel)?.reportValidity();
      return;
    }

    this.indicators()[this.currentIndex]?.classList.remove("is-error");
    this.showStep(this.currentIndex + 1);
  }

  private showStep(index: number): void {
    const panels = this.panels();
    this.currentIndex = Math.max(0, Math.min(index, panels.length - 1));

    panels.forEach((panel, panelIndex) => {
      panel.hidden = panelIndex !== this.currentIndex;
    });
    this.indicators().forEach((indicator, indicatorIndex) => {
      indicator.classList.toggle("is-complete", indicatorIndex < this.currentIndex);
      if (indicatorIndex === this.currentIndex) indicator.setAttribute("aria-current", "step");
      else indicator.removeAttribute("aria-current");
      if (indicatorIndex > this.currentIndex) indicator.setAttribute("aria-disabled", "true");
      else indicator.removeAttribute("aria-disabled");
    });

    const navigation = this.root.querySelector<HTMLElement>("[data-om-step-navigation]");
    const previous = this.root.querySelector<HTMLButtonElement>("[data-om-step-previous]");
    const next = this.root.querySelector<HTMLButtonElement>("[data-om-step-next]");
    if (navigation) navigation.hidden = false;
    if (previous) previous.hidden = this.currentIndex === 0;
    if (next) next.hidden = this.currentIndex === panels.length - 1;
    const actions = this.form?.querySelector<HTMLElement>("[data-om-form-actions]");
    if (actions) actions.hidden = this.currentIndex !== panels.length - 1;
  }

  private showFirstInvalidStep(controls?: HTMLElement[]): void {
    const panels = this.panels();
    const invalid = controls ?? Array.from(this.form?.querySelectorAll<HTMLElement>("[aria-invalid='true']") ?? []);
    const indexes = new Set(invalid.map((control) => panels.findIndex((panel) => panel.contains(control))).filter((index) => index >= 0));
    this.indicators().forEach((indicator, index) => indicator.classList.toggle("is-error", indexes.has(index)));
    const first = Math.min(...indexes);
    if (Number.isFinite(first)) this.showStep(first);
  }

  private validator(): FormValidator | null {
    const root = this.form?.querySelector<HTMLElement>("[data-om-component='form-validator']");
    const component = root && this.manager?.get(root);
    return component instanceof FormValidator ? component : null;
  }

  private validateNativeControls(panel: HTMLElement): boolean {
    return !this.firstInvalidControl(panel);
  }

  private firstInvalidControl(panel: HTMLElement): HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null {
    return Array.from(panel.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input, select, textarea"))
      .find((control) => !control.checkValidity()) ?? null;
  }

  private panels(): HTMLElement[] {
    return Array.from(this.root.querySelectorAll<HTMLElement>(PANEL_SELECTOR));
  }

  private indicators(): HTMLElement[] {
    return Array.from(this.root.querySelectorAll<HTMLElement>(INDICATOR_SELECTOR));
  }
}
