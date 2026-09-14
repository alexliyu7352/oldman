import "./feedback.scss";
import Swal, { type SweetAlertOptions, type SweetAlertResult } from "sweetalert2";
import Toastify, { type ToastifyInstance } from "toastify-js";
import { Component, type ComponentOptions } from "../core/component/component";

export type FeedbackOptions = SweetAlertOptions;
export type FeedbackResult<T = unknown> = SweetAlertResult<T>;

export type FeedbackAlertOptions = FeedbackOptions & {
  title: string;
};

export type FeedbackConfirmOptions = FeedbackOptions & {
  cancelButtonText?: string;
  confirmButtonText?: string;
  text?: string;
  title: string;
};

export type FeedbackPromptOptions = FeedbackOptions & {
  input?: SweetAlertOptions["input"];
  title: string;
};

export interface FeedbackToastOptions {
  close?: boolean;
  duration?: number;
  html?: string;
  icon?: SweetAlertOptions["icon"];
  onClick?: () => void;
  text?: string;
  title?: string;
  titleText?: string;
}

export type FeedbackLoadingOptions = FeedbackOptions & {
  title?: string;
};

/**
 * 提供后台页面常用反馈 API，并把轻提示和弹窗纳入同一页面生命周期。
 */
export class Feedback extends Component {
  static readonly componentName = "feedback";
  private readonly activeToasts = new Set<ToastifyInstance>();

  /**
   * 创建反馈组件；组件不要求特定 DOM 结构，root 只用于生命周期和事件上下文。
   */
  constructor(root: HTMLElement, options: ComponentOptions = {}) {
    super(root, options);
  }

  /**
   * 页面卸载时关闭仍在显示的轻提示和弹窗，避免 Turbo 切页后残留界面。
   */
  override async unmount(): Promise<void> {
    for (const toast of this.activeToasts) toast.hideToast();
    this.activeToasts.clear();
    this.close();
  }

  /**
   * 使用完整配置显示一次反馈弹窗。
   */
  fire<T = unknown>(options: FeedbackOptions): Promise<FeedbackResult<T>> {
    return Promise.resolve(Swal.fire<T>(this.mergeOptions(options))) as Promise<FeedbackResult<T>>;
  }

  /**
   * 显示普通提示弹窗。
   */
  alert(options: string | FeedbackAlertOptions): Promise<FeedbackResult> {
    const normalizedOptions = typeof options === "string" ? { title: options } : options;
    return this.fire(normalizedOptions);
  }

  /**
   * 显示确认弹窗，并把确认结果简化为布尔值。
   */
  async confirm(options: FeedbackConfirmOptions): Promise<boolean> {
    const result = await this.fire(options);
    return result.isConfirmed;
  }

  /**
   * 显示输入弹窗，保留 SweetAlert2 的完整返回结果以便读取 value。
   */
  prompt<T = string>(options: FeedbackPromptOptions): Promise<FeedbackResult<T>> {
    return this.fire<T>({
      input: "text",
      showCancelButton: true,
      ...options
    } as FeedbackOptions);
  }

  /**
   * 显示 toast 样式的轻量提示。
   */
  async toast(options: FeedbackToastOptions): Promise<void> {
    let toast: ToastifyInstance;
    toast = Toastify({
      callback: () => this.activeToasts.delete(toast),
      className: `om-toast om-toast-${toastTone(options.icon)}`,
      close: options.close ?? true,
      duration: options.duration ?? 3000,
      gravity: "top",
      node: toastContent(options),
      position: "right",
      stopOnFocus: true,
      ...(options.onClick ? { onClick: options.onClick } : {})
    });
    this.activeToasts.add(toast);
    toast.showToast();
  }

  /**
   * 显示加载态弹窗；调用方可以等待异步任务后主动 close。
   */
  loading(options: FeedbackLoadingOptions = {}): Promise<FeedbackResult> {
    return this.fire({
      allowEscapeKey: false,
      allowOutsideClick: false,
      didOpen: () => Swal.showLoading(),
      title: this.i18n.t("Loading..."),
      ...options
    });
  }

  /**
   * 关闭当前 SweetAlert2 弹窗。
   */
  close(): void {
    Swal.close();
  }

  /**
   * 返回当前是否存在可见的轻提示或弹窗。
   */
  isVisible(): boolean {
    return Swal.isVisible() || this.activeToasts.size > 0;
  }

  /**
   * 返回基础默认配置；项目适配器可以覆写这个方法注入主题 class。
   */
  protected defaultOptions(): FeedbackOptions {
    return {};
  }

  /**
   * 合并默认配置和单次调用配置，同时深度合并 customClass。
   */
  protected mergeOptions(options: FeedbackOptions): FeedbackOptions {
    const defaults = this.defaultOptions();
    const merged = {
      ...defaults,
      ...options
    } as FeedbackOptions;
    const customClass = mergeCustomClass(defaults.customClass, options.customClass);
    if (customClass) {
      return {
        ...merged,
        customClass
      } as FeedbackOptions;
    }
    return merged;
  }
}

/** Build one compact toast body while preserving the caller's explicit HTML boundary. */
function toastContent(options: FeedbackToastOptions): HTMLElement {
  const content = document.createElement("div");
  content.className = "om-toast-content";
  const title = options.titleText ?? options.title;
  if (title) {
    const heading = document.createElement("strong");
    heading.className = "om-toast-title";
    heading.textContent = title;
    content.append(heading);
  }
  if (options.html || options.text) {
    const body = document.createElement("div");
    body.className = "om-toast-body";
    if (options.html) body.innerHTML = options.html;
    else body.textContent = options.text ?? "";
    content.append(body);
  }
  return content;
}

/** Normalize SweetAlert's icon vocabulary to the four toast presentation tones. */
function toastTone(icon: SweetAlertOptions["icon"]): "error" | "info" | "success" | "warning" {
  return icon === "error" || icon === "success" || icon === "warning" ? icon : "info";
}

/**
 * 合并 SweetAlert2 customClass，保留项目默认按钮 class 并允许单次调用覆盖。
 */
function mergeCustomClass(
  defaults: SweetAlertOptions["customClass"],
  overrides: SweetAlertOptions["customClass"]
): SweetAlertOptions["customClass"] {
  if (!defaults) return overrides;
  if (!overrides) return defaults;
  if (typeof defaults === "string" || typeof overrides === "string") return overrides;

  return {
    ...defaults,
    ...overrides
  };
}
