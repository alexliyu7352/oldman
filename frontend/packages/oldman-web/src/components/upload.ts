import { integerAttribute } from "../core/dom/helpers";
import { Component, type ComponentOptions } from "../core/component/component";

const DEFAULT_INPUT_SELECTOR = "[data-om-upload-input], input[type='file']";
const DEFAULT_PREVIEW_SELECTOR = "[data-om-upload-preview]";
const DEFAULT_TEMPLATE_SELECTOR = "[data-om-upload-template]";
const DEFAULT_REMOVE_SELECTOR = "[data-om-upload-remove], [data-dz-remove]";
const BYTES_IN_KIB = 1024;
const REVOKE_OBJECT_URL_DELAY_MS = 1000;

export interface UploadOptions extends ComponentOptions {
  clickToSelect?: boolean;
  hideEmptyPreview?: boolean;
  inputSelector?: string;
  maxFiles?: number;
  maxSizeBytes?: number;
  previewSelector?: string;
  templateSelector?: string;
}

export interface UploadFileItem {
  error?: string;
  file: File;
  id: string;
  objectUrl?: string;
}

export interface UploadChangeDetail<TComponent extends Upload = Upload> {
  component: TComponent;
  files: UploadFileItem[];
}

/**
 * 基于浏览器原生 File API 的无头上传组件，提供拖拽、选择、预览和删除能力。
 */
export class Upload extends Component {
  static readonly componentName = "upload";
  private readonly configuredClickToSelect: boolean | undefined;
  private readonly configuredHideEmptyPreview: boolean | undefined;
  private readonly configuredInputSelector: string | undefined;
  private readonly configuredMaxFiles: number | undefined;
  private readonly configuredMaxSizeBytes: number | undefined;
  private readonly configuredPreviewSelector: string | undefined;
  private readonly configuredTemplateSelector: string | undefined;
  private files: UploadFileItem[] = [];
  private previewTemplate: HTMLElement | null = null;

  /**
   * 创建上传组件，可通过构造参数或 data 属性配置 input、预览容器和限制条件。
   */
  constructor(root: HTMLElement, options: UploadOptions = {}) {
    super(root, options);
    this.configuredClickToSelect = options.clickToSelect;
    this.configuredHideEmptyPreview = options.hideEmptyPreview;
    this.configuredInputSelector = options.inputSelector;
    this.configuredMaxFiles = options.maxFiles;
    this.configuredMaxSizeBytes = options.maxSizeBytes;
    this.configuredPreviewSelector = options.previewSelector;
    this.configuredTemplateSelector = options.templateSelector;
  }

  /**
   * 绑定文件选择、拖拽和删除行为。
   */
  override async mount(): Promise<void> {
    const input = this.inputElement();
    if (!input) return;

    this.captureTemplate();
    this.renderPreviews();
    this.listen(input, "change", () => {
      this.addFiles(input.files);
    });

    this.listen(this.root, "dragover", (event) => {
      event.preventDefault();
      this.root.dataset.omUploadDrag = "true";
    });
    this.listen(this.root, "dragleave", () => {
      this.root.dataset.omUploadDrag = "false";
    });
    this.listen(this.root, "drop", (event) => {
      event.preventDefault();
      this.root.dataset.omUploadDrag = "false";
      this.addFiles((event as DragEvent).dataTransfer?.files ?? null);
    });
    this.on("click", DEFAULT_REMOVE_SELECTOR, (event, target) => {
      event.preventDefault();
      this.removeFile(this.removeId(target));
    });
    this.bindExternalPreviewRemove();
    this.bindClickToSelect(input);
  }

  /**
   * 释放预览图片 URL。
   */
  override async unmount(): Promise<void> {
    for (const item of this.files) {
      this.releaseObjectUrl(item);
    }
    this.files = [];
  }

  /**
   * 返回当前组件持有的文件条目。
   */
  selectedFiles(): UploadFileItem[] {
    return [...this.files];
  }

  /**
   * 添加 FileList 或文件数组，并刷新预览。
   */
  addFiles(fileList: FileList | File[] | null): void {
    if (!fileList) return;

    const incoming = Array.from(fileList);
    if (!this.inputElement()?.multiple) {
      for (const item of this.files) this.releaseObjectUrl(item);
      this.files = [];
    }
    const maxFiles = this.maxFiles();
    const remainingSlots = maxFiles === undefined ? incoming.length : Math.max(maxFiles - this.files.length, 0);

    for (const file of incoming.slice(0, remainingSlots)) {
      this.files.push(this.createItem(file));
    }

    this.syncInputFiles();
    this.renderPreviews();
    this.emitChange();
  }

  /**
   * 按文件 id 删除一个条目并刷新预览。
   */
  removeFile(id: string): void {
    const index = this.files.findIndex((item) => item.id === id);
    if (index < 0) return;

    const [item] = this.files.splice(index, 1);
    if (item) this.releaseObjectUrl(item);
    this.syncInputFiles();
    this.renderPreviews();
    this.emitChange();
  }

  /**
   * 创建文件状态条目，并根据大小限制写入错误状态。
   */
  /**
   * 建立一条文件记录；超限的只打标记，**不阻断提交**。
   *
   * `syncInputFiles()` 会把带 error 的文件排除出原生 input，其余照常提交。前端限制是提示,
   * 服务端仍然必须自己校验——框架不假装客户端检查是一道防线。
   */
  private createItem(file: File): UploadFileItem {
    const maxSizeBytes = this.maxSizeBytes();
    const item: UploadFileItem = {
      file,
      id: crypto.randomUUID()
    };

    if (maxSizeBytes !== undefined && file.size > maxSizeBytes) {
      item.error = this.i18n.t("File is too large");
    }
    if (file.type.startsWith("image/")) {
      item.objectUrl = URL.createObjectURL(file);
    }

    return item;
  }

  /**
   * 保存预览模板并从页面移除原始模板节点。
   */
  private captureTemplate(): void {
    const template = this.templateElement();
    if (!template) return;

    this.previewTemplate = template.cloneNode(true) as HTMLElement;
    // 克隆会连 data-om-upload-template 一起带走,于是每一条渲染出来的预览都自称是模板。
    // 另一个上传组件找模板时就会捞到别人的预览,克隆之后还把它 remove() 掉——
    // 第一个控件已经选好的文件预览会在第二个控件挂载的瞬间消失。
    this.previewTemplate.removeAttribute("data-om-upload-template");
    template.remove();
  }

  /**
   * 重绘预览容器。
   */
  private renderPreviews(): void {
    const container = this.previewContainer();
    if (!container || !this.previewTemplate) return;

    if (this.hideEmptyPreview()) {
      container.hidden = this.files.length === 0;
    }
    container.replaceChildren(...this.files.map((item) => this.renderPreview(item)));
  }

  /**
   * 根据模板渲染一个文件预览。
   */
  private renderPreview(item: UploadFileItem): HTMLElement {
    const template = this.previewTemplate;
    if (!template) throw new Error("Upload preview template was not captured");

    const node = template.cloneNode(true) as HTMLElement;
    node.id = "";
    node.hidden = false;

    for (const name of node.querySelectorAll<HTMLElement>("[data-om-upload-name], [data-dz-name]")) {
      name.textContent = item.file.name;
    }
    for (const size of node.querySelectorAll<HTMLElement>("[data-om-upload-size], [data-dz-size]")) {
      size.textContent = this.formatSize(item.file.size);
    }
    for (const error of node.querySelectorAll<HTMLElement>("[data-om-upload-error], [data-dz-errormessage]")) {
      error.textContent = item.error ?? "";
      error.hidden = !item.error;
    }
    for (const image of node.querySelectorAll<HTMLImageElement>("[data-om-upload-thumbnail], [data-dz-thumbnail]")) {
      if (item.objectUrl) image.src = item.objectUrl;
    }
    for (const button of node.querySelectorAll<HTMLElement>(DEFAULT_REMOVE_SELECTOR)) {
      button.setAttribute("data-om-upload-remove", item.id);
      button.setAttribute("data-dz-remove", item.id);
    }

    return node;
  }

  private releaseObjectUrl(item: UploadFileItem): void {
    if (!item.objectUrl) return;

    const objectUrl = item.objectUrl;
    for (const image of document.querySelectorAll<HTMLImageElement>("[data-om-upload-thumbnail], [data-dz-thumbnail]")) {
      if (image.getAttribute("src") === objectUrl) {
        image.removeAttribute("src");
      }
    }
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), REVOKE_OBJECT_URL_DELAY_MS);
    delete item.objectUrl;
  }

  /**
   * 派发文件列表变化事件。
   */
  private emitChange(): void {
    this.emit<UploadChangeDetail>("om:upload:change", { component: this, files: this.selectedFiles() });
  }

  /**
   * 把组件接纳的有效文件同步给浏览器原生表单提交。
   */
  private syncInputFiles(): void {
    const input = this.inputElement();
    if (!input) return;
    if (typeof DataTransfer === "undefined") {
      console.warn("DataTransfer is unavailable; the native upload input was not synchronized");
      return;
    }

    try {
      const transfer = new DataTransfer();
      for (const item of this.files) {
        if (!item.error) transfer.items.add(item.file);
      }
      input.files = transfer.files;
    } catch (error) {
      console.warn("DataTransfer is unavailable; the native upload input was not synchronized", error);
    }
  }

  /**
   * 外置预览容器不在组件根节点内时，单独绑定删除事件。
   */
  private bindExternalPreviewRemove(): void {
    const container = this.previewContainer();
    if (!container || container === this.root || this.root.contains(container)) return;

    this.listen(container, "click", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;

      const button = target.closest<HTMLElement>(DEFAULT_REMOVE_SELECTOR);
      if (!button || !container.contains(button)) return;

      event.preventDefault();
      this.removeFile(this.removeId(button));
    });
  }

  /**
   * 在声明式开启时，点击上传区域会触发隐藏的文件选择框。
   */
  private bindClickToSelect(input: HTMLInputElement): void {
    if (!this.clickToSelect()) return;

    this.listen(this.root, "click", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target === input || target.closest(DEFAULT_REMOVE_SELECTOR)) return;
      if (target.closest("button, a")) return;

      input.click();
    });
  }

  /**
   * 从删除按钮上读取文件 id。
   */
  private removeId(target: Element): string {
    return target.getAttribute("data-om-upload-remove") ?? target.getAttribute("data-dz-remove") ?? "";
  }

  /**
   * 查找上传 input。
   */
  private inputElement(): HTMLInputElement | null {
    if (this.root instanceof HTMLInputElement) return this.root;
    return this.root.querySelector<HTMLInputElement>(this.configuredInputSelector ?? this.root.dataset.omUploadInputSelector ?? DEFAULT_INPUT_SELECTOR);
  }

  /**
   * 查找预览容器。
   */
  private previewContainer(): HTMLElement | null {
    const configured = this.configuredPreviewSelector ?? this.root.dataset.omUploadPreviewSelector;
    return this.resolveOwnOrConfigured(configured, DEFAULT_PREVIEW_SELECTOR);
  }

  /**
   * 查找预览模板。
   */
  private templateElement(): HTMLElement | null {
    const configured = this.configuredTemplateSelector ?? this.root.dataset.omUploadTemplateSelector;
    return this.resolveOwnOrConfigured(configured, DEFAULT_TEMPLATE_SELECTOR);
  }

  /**
   * 在组件根节点内查找；只有**显式配置过**选择器时才允许退回整个文档。
   *
   * 把预览容器或模板放在组件根节点之外是受支持的用法(见测试),那种写法一定会写
   * `data-om-upload-preview-selector` / `-template-selector`，意图是明确的。
   * 而默认选择器退回文档是意外的：页面上第二个上传控件会捞到第一个控件的节点。
   */
  private resolveOwnOrConfigured(configured: string | undefined, fallbackSelector: string): HTMLElement | null {
    const selector = configured ?? fallbackSelector;
    const own = this.root.querySelector<HTMLElement>(selector);
    if (own || configured === undefined) return own;
    return document.querySelector<HTMLElement>(selector);
  }

  /**
   * 返回最大文件数量限制。
   */
  private maxFiles(): number | undefined {
    const input = this.inputElement();
    const declared = this.configuredMaxFiles ?? integerAttribute(this.root, "data-om-upload-max-files");
    const inputDeclared = input?.getAttribute("data-max-files");
    const limit = declared ?? (inputDeclared ? Number(inputDeclared) : undefined);
    return input?.multiple ? limit : Math.min(limit ?? 1, 1);
  }

  /**
   * 判断是否点击上传区域打开文件选择框。
   */
  private clickToSelect(): boolean {
    return this.configuredClickToSelect ?? this.booleanAttribute("data-om-upload-click-select");
  }

  /**
   * 判断空预览容器是否需要隐藏。
   */
  private hideEmptyPreview(): boolean {
    return this.configuredHideEmptyPreview ?? this.booleanAttribute("data-om-upload-hide-empty-preview");
  }

  /**
   * 读取布尔属性。
   */
  private booleanAttribute(name: string): boolean {
    const value = this.root.getAttribute(name);
    return value !== null && value !== "false";
  }

  /**
   * 返回单文件大小限制。
   */
  private maxSizeBytes(): number | undefined {
    const declared = this.configuredMaxSizeBytes ?? this.sizeAttribute("data-om-upload-max-size");
    const inputDeclared = this.inputElement()?.getAttribute("data-max-file-size");
    return declared ?? this.parseSize(inputDeclared);
  }

  /**
   * 读取整数属性。
   */
  /**
   * 读取尺寸属性并转换为字节。
   */
  private sizeAttribute(name: string): number | undefined {
    return this.parseSize(this.root.getAttribute(name));
  }

  /**
   * 将 3MB、512KB 或纯数字转换为字节。
   */
  private parseSize(value: string | null | undefined): number | undefined {
    if (!value) return undefined;

    const match = value.trim().match(/^(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?$/i);
    if (!match) return undefined;

    const amountText = match[1];
    if (!amountText) return undefined;

    const amount = Number(amountText);
    const unit = (match[2] ?? "b").toLocaleLowerCase();
    if (!Number.isFinite(amount)) return undefined;

    if (unit === "gb") return amount * BYTES_IN_KIB * BYTES_IN_KIB * BYTES_IN_KIB;
    if (unit === "mb") return amount * BYTES_IN_KIB * BYTES_IN_KIB;
    if (unit === "kb") return amount * BYTES_IN_KIB;
    return amount;
  }

  /**
   * 格式化预览中的文件大小。
   */
  private formatSize(size: number): string {
    if (size >= BYTES_IN_KIB * BYTES_IN_KIB) return `${(size / BYTES_IN_KIB / BYTES_IN_KIB).toFixed(1)} MB`;
    if (size >= BYTES_IN_KIB) return `${(size / BYTES_IN_KIB).toFixed(1)} KB`;
    return `${size} B`;
  }
}
