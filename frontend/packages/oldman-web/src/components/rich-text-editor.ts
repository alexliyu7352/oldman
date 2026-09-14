import Quill from "quill";
import "quill/dist/quill.snow.css";
import "./rich-text-editor.scss";
import { Component } from "../core/component/component";

/** 用 Quill 增强原生 textarea，提交值始终保存在 textarea 中。 */
export class RichTextEditor extends Component {
  static readonly componentName = "rich-text-editor";
  private editor: HTMLElement | null = null;
  private editorClassName = "";
  private initialValue = "";
  private quill: Quill | null = null;
  private textarea: HTMLTextAreaElement | null = null;
  private textareaRequired = false;
  private readonly syncValue = (): void => {
    if (!this.quill || !this.textarea) return;
    this.textarea.value = this.quill.getText().trim() ? this.quill.root.innerHTML : "";
    this.textarea.dispatchEvent(new Event("input", { bubbles: true }));
  };

  override async mount(): Promise<void> {
    const textarea = this.root.querySelector<HTMLTextAreaElement>("[data-om-rich-text-value]");
    const editor = this.root.querySelector<HTMLElement>("[data-om-rich-text-editor]");
    if (!textarea || !editor) throw new Error("RichTextEditor requires a textarea and editor element");

    this.textarea = textarea;
    this.editor = editor;
    this.editorClassName = editor.className;
    this.initialValue = textarea.value;
    this.textareaRequired = textarea.required;
    textarea.required = false;
    textarea.hidden = true;
    editor.hidden = false;

    this.quill = new Quill(editor, {
      readOnly: textarea.disabled || textarea.readOnly,
      theme: "snow",
      modules: {
        toolbar: [
          [{ header: [1, 2, 3, false] }],
          ["bold", "italic", "underline", "strike"],
          [{ list: "ordered" }, { list: "bullet" }],
          ["blockquote", "code-block", "link"],
          ["clean"]
        ]
      }
    });
    this.localizeToolbar();
    this.listen(document, "om:i18n:change", () => this.localizeToolbar());
    this.setEditorValue(this.initialValue);
    this.quill.on("text-change", this.syncValue);
    this.listen(textarea.form ?? this.root, "reset", () => {
      queueMicrotask(() => this.setEditorValue(this.initialValue));
    });
  }

  override async unmount(): Promise<void> {
    this.quill?.off("text-change", this.syncValue);
    this.root.querySelector(":scope > .ql-toolbar")?.remove();
    if (this.editor) {
      this.editor.className = this.editorClassName;
      this.editor.replaceChildren();
      this.editor.hidden = true;
    }
    if (this.textarea) {
      this.textarea.hidden = false;
      this.textarea.required = this.textareaRequired;
    }
    this.quill = null;
    this.editor = null;
    this.textarea = null;
  }

  /** 恢复或初始化编辑内容，并保持真实 textarea 同步。 */
  private setEditorValue(value: string): void {
    if (!this.quill || !this.textarea) return;
    this.quill.clipboard.dangerouslyPasteHTML(value, "silent");
    this.textarea.value = value;
  }

  /** Translate Quill's generated toolbar without maintaining a second toolbar implementation. */
  private localizeToolbar(): void {
    const toolbar = this.root.querySelector<HTMLElement>(":scope > .ql-toolbar");
    if (!toolbar) return;

    const header = toolbar.querySelector<HTMLElement>(".ql-picker.ql-header");
    if (header) {
      const labels = new Map([
        ["", this.i18n.tc("Rich text editor toolbar", "Normal")],
        ["1", this.i18n.tc("Rich text editor toolbar", "Heading 1")],
        ["2", this.i18n.tc("Rich text editor toolbar", "Heading 2")],
        ["3", this.i18n.tc("Rich text editor toolbar", "Heading 3")]
      ]);
      for (const item of header.querySelectorAll<HTMLElement>(".ql-picker-item")) {
        item.dataset.label = labels.get(item.dataset.value ?? "") ?? "";
      }
      const label = header.querySelector<HTMLElement>(".ql-picker-label");
      if (label) {
        label.dataset.label = header.querySelector<HTMLElement>(".ql-picker-item.ql-selected")?.dataset.label ?? labels.get("")!;
        label.setAttribute("aria-label", this.i18n.tc("Rich text editor toolbar", "Text style"));
      }
    }

    const buttonLabels = [
      [".ql-bold", this.i18n.tc("Rich text editor toolbar", "Bold")],
      [".ql-italic", this.i18n.tc("Rich text editor toolbar", "Italic")],
      [".ql-underline", this.i18n.tc("Rich text editor toolbar", "Underline")],
      [".ql-strike", this.i18n.tc("Rich text editor toolbar", "Strikethrough")],
      ['.ql-list[value="ordered"]', this.i18n.tc("Rich text editor toolbar", "Ordered list")],
      ['.ql-list[value="bullet"]', this.i18n.tc("Rich text editor toolbar", "Bullet list")],
      [".ql-blockquote", this.i18n.tc("Rich text editor toolbar", "Blockquote")],
      [".ql-code-block", this.i18n.tc("Rich text editor toolbar", "Code block")],
      [".ql-link", this.i18n.tc("Rich text editor toolbar", "Link")],
      [".ql-clean", this.i18n.tc("Rich text editor toolbar", "Clear formatting")]
    ] as const;
    for (const [selector, label] of buttonLabels) {
      for (const button of toolbar.querySelectorAll<HTMLElement>(selector)) {
        button.title = label;
        button.setAttribute("aria-label", label);
      }
    }
  }
}
