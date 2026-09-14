import { Component } from "../core/component/component";

/** Preview SlugField normalization while keeping the server authoritative. */
export class SlugInput extends Component {
  static readonly componentName = "slug-input";
  private generatedValue = "";
  private automatic = false;

  override async mount(): Promise<void> {
    const target = this.target();
    this.automatic = target.value.length === 0;
    this.listen(target, "input", () => this.onTargetInput());

    const source = this.source();
    if (!source) return;
    this.listen(source, "input", () => this.updateFromSource());
    if (this.automatic) this.updateFromSource();
  }

  private onTargetInput(): void {
    const target = this.target();
    const normalized = this.slugify(target.value);
    if (target.value !== normalized) target.value = normalized;
    this.automatic = normalized.length === 0 || normalized === this.generatedValue;
    if (normalized.length === 0) this.updateFromSource();
  }

  private updateFromSource(): void {
    if (!this.automatic) return;
    const source = this.source();
    if (!source) return;
    this.generatedValue = this.slugify(source.value);
    this.target().value = this.generatedValue;
  }

  private slugify(value: string): string {
    const unicode = this.root.dataset.omSlugAllowUnicode === "true";
    const normalized = value.normalize(unicode ? "NFKC" : "NFKD").toLowerCase();
    const text = unicode
      ? normalized.replace(/[^\p{Letter}\p{Number}]+/gu, "-")
      : normalized.replace(/\p{Mark}/gu, "").replace(/[^a-z0-9]+/g, "-");
    return text.replace(/^-+|-+$/g, "");
  }

  private source(): HTMLInputElement | null {
    const selector = this.root.dataset.omSlugSource;
    if (!selector) return null;
    return this.root.closest("form")?.querySelector<HTMLInputElement>(selector) ?? null;
  }

  private target(): HTMLInputElement {
    if (!(this.root instanceof HTMLInputElement)) throw new Error("SlugInput requires an input");
    return this.root;
  }
}
