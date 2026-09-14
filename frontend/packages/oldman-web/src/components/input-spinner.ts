import { Component } from "../core/component/component";

const INPUT_SELECTOR = "[data-om-input-spinner-input]";

/** Add accessible buttons around a native number input without changing submission semantics. */
export class InputSpinner extends Component {
  static readonly componentName = "input-spinner";

  override async mount(): Promise<void> {
    const input = this.input();
    if (!input || input.type !== "number") throw new Error("InputSpinner requires a number input");

    this.on("click", "[data-om-input-spinner-decrease]", (event) => {
      event.preventDefault();
      this.step(-1);
    });
    this.on("click", "[data-om-input-spinner-increase]", (event) => {
      event.preventDefault();
      this.step(1);
    });
    this.listen(input, "input", () => this.updateButtons());
    this.updateButtons();
  }

  private step(direction: -1 | 1): void {
    const input = this.input();
    if (!input || input.disabled || input.readOnly) return;
    if (direction < 0) input.stepDown();
    else input.stepUp();
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  private updateButtons(): void {
    const input = this.input();
    if (!input) return;
    const value = input.valueAsNumber;
    const unavailable = input.disabled || input.readOnly;
    const decrease = this.root.querySelector<HTMLButtonElement>("[data-om-input-spinner-decrease]");
    const increase = this.root.querySelector<HTMLButtonElement>("[data-om-input-spinner-increase]");
    if (decrease) decrease.disabled = unavailable || Number.isFinite(value) && input.min !== "" && value <= Number(input.min);
    if (increase) increase.disabled = unavailable || Number.isFinite(value) && input.max !== "" && value >= Number(input.max);
  }

  private input(): HTMLInputElement | null {
    return this.root.querySelector<HTMLInputElement>(INPUT_SELECTOR);
  }
}
