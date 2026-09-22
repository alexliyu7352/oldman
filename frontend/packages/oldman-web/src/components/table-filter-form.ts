import { Form } from "./form";
import { Table } from "./table";

const TABLE_TARGET_ATTRIBUTE = "data-om-table-target";
const FILTER_RESET_SELECTOR = "[data-om-filter-reset]";

export interface TableFilterFormSubmitDetail<TForm extends TableFilterForm = TableFilterForm> {
  component: TForm;
  form: HTMLFormElement;
  table: Table;
}

export interface TableFilterFormSubmitErrorDetail<TForm extends TableFilterForm = TableFilterForm> {
  component: TForm;
  error: unknown;
  form: HTMLFormElement;
}

/**
 * 表格筛选表单组件：只处理自身提交，并通过组件管理器调用目标 Table API。
 */
export class TableFilterForm extends Form {
  static override readonly componentName = "table-filter-form";

  override async mount(): Promise<void> {
    this.on("click", FILTER_RESET_SELECTOR, (event, trigger) => {
      event.preventDefault();
      const form = trigger.closest("form") ?? this.formElement();
      void this.resetFilterForm(form).catch(() => undefined);
    });

    if (this.root instanceof HTMLFormElement) {
      this.listen(this.root, "submit", (event) => {
        event.preventDefault();
        void this.submitFilterForm(this.root as HTMLFormElement).catch(() => undefined);
      });
      return;
    }

    this.on("submit", "form", (event, matchedElement) => {
      event.preventDefault();
      const form = matchedElement instanceof HTMLFormElement ? matchedElement : event.target;
      if (!(form instanceof HTMLFormElement)) return;
      void this.submitFilterForm(form).catch(() => undefined);
    });
  }

  /**
   * 提交当前筛选表单，并把刷新动作交给目标 Table。
   */
  async submitFilterForm(form = this.formElement()): Promise<void> {
    this.clearFormErrors();
    this.setStatus("loading", this.i18n.t("Loading..."));

    try {
      const table = this.resolveTargetTable(form);
      await table.applyFilterForm(form);
      this.setStatus("success");
      this.emit<TableFilterFormSubmitDetail>("om:table-filter-form:success", { component: this, form, table });
    } catch (error) {
      this.setStatus("error", error instanceof Error ? error.message : this.i18n.t("Request failed"));
      this.emit<TableFilterFormSubmitErrorDetail>("om:table-filter-form:error", { component: this, error, form });
      throw error;
    }
  }

  /**
   * 清空所有筛选值（不是 form.reset()：服务端渲染的 value 就是当前筛选）并重新提交。
   */
  async resetFilterForm(form = this.formElement()): Promise<void> {
    for (const control of form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input, select, textarea")) {
      if (control instanceof HTMLInputElement) {
        if (control.type === "hidden" || control.type === "submit" || control.type === "button") continue;
        if (control.type === "checkbox" || control.type === "radio") control.checked = false;
        else control.value = "";
      } else if (control instanceof HTMLSelectElement) {
        control.selectedIndex = control.multiple ? -1 : 0;
        if (!control.multiple && control.options.length > 0 && control.options[0]!.value !== "") control.selectedIndex = -1;
      } else {
        control.value = "";
      }
      control.dispatchEvent(new Event("input", { bubbles: true }));
      control.dispatchEvent(new Event("change", { bubbles: true }));
    }
    await this.submitFilterForm(form);
  }

  private formElement(): HTMLFormElement {
    if (this.root instanceof HTMLFormElement) return this.root;
    const form = this.root.querySelector<HTMLFormElement>("form");
    if (!form) throw new Error("TableFilterForm requires a form element");
    return form;
  }

  private resolveTargetTable(form: HTMLFormElement): Table {
    const selector = form.getAttribute(TABLE_TARGET_ATTRIBUTE) || this.root.getAttribute(TABLE_TARGET_ATTRIBUTE);
    if (!selector) throw new Error("TableFilterForm requires data-om-table-target");
    if (!this.manager) throw new Error("TableFilterForm requires a component manager");

    const component = this.manager.get(selector);
    if (!(component instanceof Table)) {
      throw new Error(`No Table component mounted for ${selector}`);
    }
    return component;
  }
}
