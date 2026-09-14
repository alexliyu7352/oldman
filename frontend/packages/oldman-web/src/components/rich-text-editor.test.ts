import { afterEach, describe, expect, it, vi } from "vitest";
import { createI18n } from "../core/i18n";

const quillMock = vi.hoisted(() => {
  const handlers = new Map<string, () => void>();
  const editor = document.createElement("div");
  const instance = {
    clipboard: {
      dangerouslyPasteHTML: vi.fn((value: string) => {
        editor.innerHTML = value;
      })
    },
    getText: vi.fn(() => editor.textContent ?? ""),
    off: vi.fn(),
    on: vi.fn((name: string, callback: () => void) => handlers.set(name, callback)),
    root: editor
  };
  return { handlers, instance };
});

vi.mock("quill", () => ({
  default: vi.fn(function (container: HTMLElement) {
    const toolbar = document.createElement("div");
    toolbar.className = "ql-toolbar";
    toolbar.innerHTML = `
      <span class="ql-picker ql-header">
        <span class="ql-picker-label"></span>
        <span class="ql-picker-options">
          <span class="ql-picker-item ql-selected"></span>
          <span class="ql-picker-item" data-value="1"></span>
          <span class="ql-picker-item" data-value="2"></span>
          <span class="ql-picker-item" data-value="3"></span>
        </span>
      </span>
      <button class="ql-bold"></button>
      <button class="ql-list" value="ordered"></button>
    `;
    container.before(toolbar);
    container.append(quillMock.instance.root);
    return quillMock.instance;
  })
}));

import { RichTextEditor } from "./rich-text-editor";

describe("RichTextEditor", () => {
  afterEach(() => {
    document.body.replaceChildren();
    quillMock.handlers.clear();
    quillMock.instance.root.replaceChildren();
    vi.clearAllMocks();
  });

  it("syncs Quill HTML to the textarea and restores the native control", async () => {
    document.body.innerHTML = `
      <form>
        <div data-om-component="rich-text-editor">
          <textarea name="body" required data-om-rich-text-value><p>Initial</p></textarea>
          <div class="om-rich-text-editor" data-om-rich-text-editor hidden></div>
        </div>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='rich-text-editor']")!;
    const textarea = root.querySelector<HTMLTextAreaElement>("textarea")!;
    const component = new RichTextEditor(root);

    await component.start();
    expect(textarea.hidden).toBe(true);
    expect(textarea.required).toBe(false);

    quillMock.instance.root.innerHTML = "<p>Changed</p>";
    quillMock.handlers.get("text-change")?.();
    expect(textarea.value).toBe("<p>Changed</p>");

    root.closest("form")?.reset();
    await Promise.resolve();
    expect(textarea.value).toBe("<p>Initial</p>");

    await component.stop();
    expect(quillMock.instance.off).toHaveBeenCalledWith("text-change", expect.any(Function));
    expect(textarea.hidden).toBe(false);
    expect(textarea.required).toBe(true);
  });

  it("localizes Quill's generated heading picker and toolbar buttons", async () => {
    document.body.innerHTML = `
      <div data-om-component="rich-text-editor">
        <textarea data-om-rich-text-value></textarea>
        <div class="om-rich-text-editor" data-om-rich-text-editor hidden></div>
      </div>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='rich-text-editor']")!;
    const component = new RichTextEditor(root, {
      i18n: createI18n({
        locale: "zh-Hans",
        messages: {
          "Rich text editor toolbar\u0004Bold": "粗体",
          "Rich text editor toolbar\u0004Heading 1": "一级标题",
          "Rich text editor toolbar\u0004Heading 2": "二级标题",
          "Rich text editor toolbar\u0004Heading 3": "三级标题",
          "Rich text editor toolbar\u0004Normal": "正文",
          "Rich text editor toolbar\u0004Ordered list": "有序列表",
          "Rich text editor toolbar\u0004Text style": "文本样式"
        }
      })
    });

    await component.start();
    const header = root.querySelector<HTMLElement>(".ql-picker.ql-header")!;
    expect(header.querySelector<HTMLElement>(".ql-picker-label")?.dataset.label).toBe("正文");
    expect(Array.from(header.querySelectorAll<HTMLElement>(".ql-picker-item"), (item) => item.dataset.label)).toEqual([
      "正文",
      "一级标题",
      "二级标题",
      "三级标题"
    ]);
    expect(root.querySelector<HTMLElement>(".ql-bold")?.getAttribute("aria-label")).toBe("粗体");
    expect(root.querySelector<HTMLElement>('.ql-list[value="ordered"]')?.title).toBe("有序列表");

    await component.stop();
  });
});
