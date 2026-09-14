import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Upload } from "./upload";

let nativeFilesDescriptor: PropertyDescriptor;

describe("Upload", () => {
  beforeEach(() => {
    nativeFilesDescriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "files")!;
    const files = new WeakMap<HTMLInputElement, FileList>();
    Object.defineProperty(HTMLInputElement.prototype, "files", {
      configurable: true,
      get(this: HTMLInputElement): FileList {
        return files.get(this) ?? fileList([]);
      },
      set(this: HTMLInputElement, value: FileList): void {
        files.set(this, value);
      }
    });
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => `file-${Math.random()}`) });
    vi.stubGlobal("DataTransfer", TestDataTransfer);
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:preview"),
      revokeObjectURL: vi.fn()
    });
  });

  afterEach(() => {
    Object.defineProperty(HTMLInputElement.prototype, "files", nativeFilesDescriptor);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  it("选择文件后渲染预览并派发变更事件", async () => {
    document.body.innerHTML = uploadMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new Upload(root);
    let changeCount = 0;

    root.addEventListener("om:upload:change", () => {
      changeCount += 1;
    });
    await component.start();

    setFiles(input, [new File(["hello"], "hello.txt", { type: "text/plain" })]);
    input.dispatchEvent(new Event("change", { bubbles: true }));

    expect(component.selectedFiles()).toHaveLength(1);
    expect(root.querySelector("[data-om-upload-preview]")?.textContent).toContain("hello.txt");
    expect(changeCount).toBe(1);

    await component.stop();
  });

  it("支持拖拽添加、最大数量限制和删除", async () => {
    document.body.innerHTML = uploadMarkup(`data-om-upload-max-files="1"`);
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new Upload(root);
    await component.start();

    const dropEvent = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, "dataTransfer", { value: { files: fileList([
      new File(["one"], "one.txt", { type: "text/plain" }),
      new File(["two"], "two.txt", { type: "text/plain" })
    ]) } });
    root.dispatchEvent(dropEvent);

    expect(component.selectedFiles()).toHaveLength(1);
    expect(Array.from(input.files ?? [], (file) => file.name)).toEqual(["one.txt"]);
    expect(root.textContent).toContain("one.txt");
    root.querySelector<HTMLButtonElement>("[data-om-upload-remove]")!.click();
    expect(component.selectedFiles()).toHaveLength(0);
    expect(input.files).toHaveLength(0);
    expect(root.querySelector("[data-om-upload-preview]")?.textContent).not.toContain("one.txt");

    await component.stop();
  });

  it("支持组件根节点外部的预览容器删除文件", async () => {
    document.body.innerHTML = `
      <section data-om-component="upload" data-om-upload-preview-selector="#external-preview" data-om-upload-template-selector="#external-template">
        <input type="file" data-om-upload-input multiple>
      </section>
      <ul id="external-preview"></ul>
      <li id="external-template" data-om-upload-template hidden>
        <span data-om-upload-name></span>
        <button type="button" data-om-upload-remove>Delete</button>
      </li>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const component = new Upload(root);
    await component.start();

    component.addFiles([new File(["external"], "external.txt", { type: "text/plain" })]);
    expect(document.querySelector("#external-preview")?.textContent).toContain("external.txt");

    document.querySelector<HTMLButtonElement>("#external-preview [data-om-upload-remove]")!.click();
    expect(component.selectedFiles()).toHaveLength(0);
    expect(document.querySelector("#external-preview")?.textContent).not.toContain("external.txt");

    await component.stop();
  });

  it("支持点击上传区域触发隐藏文件选择框", async () => {
    document.body.innerHTML = uploadMarkup(`data-om-upload-click-select="true"`);
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new Upload(root);
    const clickSpy = vi.spyOn(input, "click").mockImplementation(() => {});
    await component.start();

    root.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(clickSpy).toHaveBeenCalledTimes(1);

    await component.stop();
  });

  it("支持空预览容器隐藏并在文件变化时恢复", async () => {
    document.body.innerHTML = uploadMarkup(`data-om-upload-hide-empty-preview="true"`);
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const preview = root.querySelector<HTMLElement>("[data-om-upload-preview]")!;
    const component = new Upload(root);
    await component.start();

    expect(preview.hidden).toBe(true);
    component.addFiles([new File(["one"], "one.txt", { type: "text/plain" })]);
    expect(preview.hidden).toBe(false);

    root.querySelector<HTMLButtonElement>("[data-om-upload-remove]")!.click();
    expect(preview.hidden).toBe(true);

    await component.stop();
  });

  it("标记超过大小限制的文件并释放图片预览 URL", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = uploadMarkup(`data-om-upload-max-size="3B"`);
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new Upload(root);
    try {
      await component.start();

      component.addFiles([new File(["image"], "avatar.png", { type: "image/png" })]);

      expect(component.selectedFiles()[0]?.error).toBe("File is too large");
      expect(input.files).toHaveLength(0);
      expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
      expect(root.querySelector<HTMLImageElement>("[data-om-upload-thumbnail]")?.getAttribute("src")).toBe("blob:preview");

      await component.stop();
      expect(root.querySelector<HTMLImageElement>("[data-om-upload-thumbnail]")?.hasAttribute("src")).toBe(false);
      expect(URL.revokeObjectURL).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1000);
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
      expect(component.selectedFiles()).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("多次选择时把全部有效文件同步给原生 input", async () => {
    document.body.innerHTML = uploadMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new Upload(root);
    await component.start();

    setFiles(input, [new File(["one"], "one.txt", { type: "text/plain" })]);
    input.dispatchEvent(new Event("change", { bubbles: true }));
    setFiles(input, [new File(["two"], "two.txt", { type: "text/plain" })]);
    input.dispatchEvent(new Event("change", { bubbles: true }));

    expect(Array.from(input.files ?? [], (file) => file.name)).toEqual(["one.txt", "two.txt"]);

    await component.stop();
  });

  it("单文件 input 再次选择时替换原文件", async () => {
    document.body.innerHTML = uploadMarkup().replace(" multiple>", ">");
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new Upload(root);
    await component.start();

    setFiles(input, [new File(["one"], "one.txt", { type: "text/plain" })]);
    input.dispatchEvent(new Event("change", { bubbles: true }));
    setFiles(input, [new File(["two"], "two.txt", { type: "text/plain" })]);
    input.dispatchEvent(new Event("change", { bubbles: true }));

    expect(component.selectedFiles().map((item) => item.file.name)).toEqual(["two.txt"]);
    expect(Array.from(input.files ?? [], (file) => file.name)).toEqual(["two.txt"]);

    await component.stop();
  });

  it("单文件 input 拖放新文件时替换原文件", async () => {
    document.body.innerHTML = uploadMarkup().replace(" multiple>", ">");
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new Upload(root);
    await component.start();

    setFiles(input, [new File(["one"], "one.txt", { type: "text/plain" })]);
    input.dispatchEvent(new Event("change", { bubbles: true }));
    const dropEvent = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: { files: fileList([new File(["two"], "two.txt", { type: "text/plain" })]) }
    });
    root.dispatchEvent(dropEvent);

    expect(component.selectedFiles().map((item) => item.file.name)).toEqual(["two.txt"]);
    expect(Array.from(input.files ?? [], (file) => file.name)).toEqual(["two.txt"]);

    await component.stop();
  });

  it("DataTransfer 不可用时保留浏览器原生选择", async () => {
    vi.stubGlobal("DataTransfer", class {
      constructor() {
        throw new Error("unavailable");
      }
    });
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
    document.body.innerHTML = uploadMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='upload']")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const selected = new File(["native"], "native.txt", { type: "text/plain" });
    const component = new Upload(root);
    await component.start();
    setFiles(input, [selected]);

    expect(() => component.addFiles(input.files)).not.toThrow();
    expect(Array.from(input.files ?? [], (file) => file.name)).toEqual(["native.txt"]);
    expect(warning).toHaveBeenCalledOnce();

    await component.stop();
  });
});

class TestDataTransfer {
  private readonly values: File[] = [];
  readonly items = {
    add: (file: File): null => {
      this.values.push(file);
      return null;
    }
  };

  get files(): FileList {
    return fileList(this.values);
  }
}

/**
 * 返回上传组件测试 DOM。
 */
function uploadMarkup(attributes = ""): string {
  return `
    <section data-om-component="upload" ${attributes}>
      <input type="file" data-om-upload-input multiple>
      <ul data-om-upload-preview>
        <li data-om-upload-template hidden>
          <span data-om-upload-name></span>
          <span data-om-upload-size></span>
          <strong data-om-upload-error></strong>
          <img data-om-upload-thumbnail alt="">
          <button type="button" data-om-upload-remove>Delete</button>
        </li>
      </ul>
    </section>
  `;
}

/**
 * 在 jsdom 中模拟 input.files。
 */
function setFiles(input: HTMLInputElement, files: File[]): void {
  Object.defineProperty(input, "files", {
    configurable: true,
    writable: true,
    value: fileList(files)
  });
}

/**
 * 构造测试所需的最小 FileList。
 */
function fileList(files: File[]): FileList {
  const values = [...files] as File[] & { item(index: number): File | null };
  values.item = (index) => values[index] ?? null;
  return values as unknown as FileList;
}
