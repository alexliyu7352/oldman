import "./select.scss";
import Choices from "choices.js";
import { Component } from "../core/component/component";

/** Enhance one delimiter-backed text input with removable tags. */
export class TagsInput extends Component {
  static readonly componentName = "tags-input";
  private choices: Choices | null = null;
  private delimiter = ",";
  private initialValue = "";

  override async mount(): Promise<void> {
    const input = this.input();
    this.delimiter = input.dataset.omTagsDelimiter ?? ",";
    if ([...this.delimiter].length !== 1) throw new Error("TagsInput delimiter must be exactly one character");

    this.initialValue = normalizeTags(input.value, this.delimiter);
    input.value = this.initialValue;
    const form = input.form;
    this.choices = new Choices(input, {
      allowHTML: false,
      allowHtmlUserInput: false,
      silent: true,
      delimiter: this.delimiter,
      duplicateItemsAllowed: false,
      editItems: false,
      removeItemButton: true,
      shouldSort: false,
      loadingText: this.i18n.t("Loading..."),
      noResultsText: this.i18n.t("No results found"),
      noChoicesText: this.i18n.t("No choices available"),
      itemSelectText: this.i18n.t("Press to select"),
      uniqueItemText: this.i18n.t("Only unique values can be added"),
      customAddItemText: this.i18n.t("Only values matching specific conditions can be added"),
      addItemText: (value) => this.i18n.t('Press Enter to add "{value}"', { value }),
      maxItemText: (count) => this.i18n.tn("{count} value can be added", "{count} values can be added", count, { count })
    });

    const editor = this.editor();
    this.listen(input, "focus", () => editor.focus());
    this.listen(input, "invalid", () => editor.focus());
    this.listen<KeyboardEvent>(editor, "keydown", (event) => {
      if (event.isComposing) {
        event.stopImmediatePropagation();
        return;
      }
      if (event.key === "Backspace" && editor.value.length === 0) {
        const last = this.values().at(-1);
        if (!last) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        this.choices?.removeActiveItemsByValue(last);
        return;
      }
      if (event.key !== "Enter" && event.key !== this.delimiter) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      this.commit(editor.value);
    }, { capture: true });
    this.listen<ClipboardEvent>(editor, "paste", (event) => {
      const text = event.clipboardData?.getData("text") ?? "";
      if (!text.includes(this.delimiter)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      this.commit(text);
    }, { capture: true });
    this.listen(editor, "blur", () => this.commit(editor.value));
    this.listen(input, "change", () => input.dispatchEvent(new Event("input", { bubbles: true })));

    if (form) {
      this.listen(form, "submit", () => this.commit(editor.value), { capture: true });
      this.listen(form, "reset", () => queueMicrotask(() => this.reset()));
    }
  }

  override async unmount(): Promise<void> {
    this.choices?.destroy();
    this.choices = null;
  }

  private commit(value: string): void {
    if (!this.choices) return;
    const current = new Set(this.values());
    const additions = splitTags(value, this.delimiter).filter((item) => !current.has(item));
    if (additions.length > 0) this.choices.setValue(additions);
    this.editor().value = "";
  }

  private reset(): void {
    if (!this.choices) return;
    this.choices.clearStore();
    const values = splitTags(this.initialValue, this.delimiter);
    if (values.length > 0) this.choices.setValue(values);
  }

  private values(): string[] {
    const value = this.choices?.getValue(true) ?? [];
    return Array.isArray(value) ? value.map(String) : [String(value)];
  }

  private editor(): HTMLInputElement {
    const editor = this.root.parentElement?.querySelector<HTMLInputElement>(".choices__input--cloned");
    if (!editor) throw new Error("TagsInput editor is unavailable");
    return editor;
  }

  private input(): HTMLInputElement {
    if (!(this.root instanceof HTMLInputElement)) throw new Error("TagsInput requires an input");
    return this.root;
  }
}

function normalizeTags(value: string, delimiter: string): string {
  return splitTags(value, delimiter).join(delimiter);
}

function splitTags(value: string, delimiter: string): string[] {
  return [...new Set(value.split(delimiter).map((item) => item.trim()).filter(Boolean))];
}
