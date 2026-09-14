import { Component } from "../core/component/component";

const INDEXED_ATTRIBUTES = ["name", "id", "for", "aria-describedby", "aria-controls", "data-om-error-for"] as const;

/** Maintain a scalar FieldList's rows and browser field identifiers. */
export class FormRepeater extends Component {
  static readonly componentName = "form-repeater";

  override async mount(): Promise<void> {
    this.on("click", "[data-om-repeater-add]", (event) => {
      event.preventDefault();
      void this.addRow();
    });
    this.on("click", "[data-om-repeater-remove]", (event, button) => {
      event.preventDefault();
      void this.removeRow(button.closest<HTMLElement>("[data-om-repeater-row]"));
    });
    this.on("click", "[data-om-repeater-up]", (event, button) => {
      event.preventDefault();
      this.moveRow(button.closest<HTMLElement>("[data-om-repeater-row]"), -1);
    });
    this.on("click", "[data-om-repeater-down]", (event, button) => {
      event.preventDefault();
      this.moveRow(button.closest<HTMLElement>("[data-om-repeater-row]"), 1);
    });
    this.reindex();
  }

  private async addRow(): Promise<void> {
    const rows = this.rows();
    if (rows.length >= this.limit("max", Number.POSITIVE_INFINITY)) return;

    const template = this.root.querySelector<HTMLTemplateElement>("[data-om-repeater-template]");
    const row = template?.content.firstElementChild?.cloneNode(true);
    if (!(row instanceof HTMLElement)) return;

    this.rowsContainer()?.append(row);
    this.reindex();
    await this.manager?.mount(this.root);
  }

  private async removeRow(row: HTMLElement | null): Promise<void> {
    if (!row || this.rows().length <= this.limit("min", 0)) return;
    await this.manager?.unmount(row);
    row.remove();
    this.reindex();
  }

  private moveRow(row: HTMLElement | null, offset: -1 | 1): void {
    if (!row) return;
    const rows = this.rows();
    const current = rows.indexOf(row);
    const destination = current + offset;
    if (current < 0 || destination < 0 || destination >= rows.length) return;

    const destinationRow = rows[destination];
    if (!destinationRow) return;
    if (offset < 0) destinationRow.before(row);
    else destinationRow.after(row);
    this.reindex();
  }

  private reindex(): void {
    const rows = this.rows();
    rows.forEach((row, index) => {
      row.dataset.omRepeaterIndex = String(index);
      for (const element of Array.from(row.querySelectorAll<HTMLElement>("*"))) {
        for (const attribute of INDEXED_ATTRIBUTES) {
          const value = element.getAttribute(attribute);
          if (value !== null) element.setAttribute(attribute, this.replaceIndex(value, index));
        }
      }
      const up = row.querySelector<HTMLButtonElement>("[data-om-repeater-up]");
      const down = row.querySelector<HTMLButtonElement>("[data-om-repeater-down]");
      const remove = row.querySelector<HTMLButtonElement>("[data-om-repeater-remove]");
      if (up) up.disabled = index === 0;
      if (down) down.disabled = index === rows.length - 1;
      if (remove) remove.disabled = rows.length <= this.limit("min", 0);
    });

    const add = this.root.querySelector<HTMLButtonElement>("[data-om-repeater-add]");
    if (add) add.disabled = rows.length >= this.limit("max", Number.POSITIVE_INFINITY);
  }

  private replaceIndex(value: string, index: number): string {
    const bases = [this.root.dataset.omRepeaterName, this.root.dataset.omRepeaterId].filter(Boolean) as string[];
    return bases.reduce(
      (current, base) => current.replace(new RegExp(`${escapeRegExp(base)}-(?:\\d+|__index__)`, "g"), `${base}-${index}`),
      value
    );
  }

  private rows(): HTMLElement[] {
    return Array.from(this.rowsContainer()?.children ?? []).filter(
      (element): element is HTMLElement => element instanceof HTMLElement && element.matches("[data-om-repeater-row]")
    );
  }

  private rowsContainer(): HTMLElement | null {
    return this.root.querySelector<HTMLElement>("[data-om-repeater-rows]");
  }

  private limit(name: "min" | "max", fallback: number): number {
    const rawValue = name === "min" ? this.root.dataset.omRepeaterMin : this.root.dataset.omRepeaterMax;
    if (rawValue === undefined) return fallback;
    const value = Number(rawValue);
    return Number.isInteger(value) && value >= 0 ? value : fallback;
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
