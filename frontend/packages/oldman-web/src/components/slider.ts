import { integerAttribute } from "../core/dom/helpers";
import "./slider.scss";
import noUiSlider, { type API as NoUiSliderApi, type Options as NoUiSliderOptions } from "nouislider";
import wNumb from "wnumb";
import { Component, type ComponentOptions } from "../core/component/component";

export type SliderOptions = ComponentOptions & {
  options?: NoUiSliderOptions;
};

export type SliderEventName = "update" | "change" | "slide" | "set";

export interface SliderEventDetail<TComponent extends Slider = Slider> {
  component: TComponent;
  handle: number;
  positions: number[];
  values: Array<number | string>;
}

/**
 * 基于 noUiSlider 的标准范围选择组件，负责初始化、销毁和事件桥接。
 */
export class Slider extends Component {
  static readonly componentName = "slider";

  private readonly configuredOptions: NoUiSliderOptions | undefined;
  private slider: NoUiSliderApi | null = null;
  private submitTimer: number | null = null;

  /**
   * 创建范围选择组件，可通过构造参数或 data-om-slider-options 提供 noUiSlider 配置。
   */
  constructor(root: HTMLElement, options: SliderOptions = {}) {
    super(root, options);
    this.configuredOptions = options.options;
  }

  /**
   * 初始化 noUiSlider，并桥接常用运行时事件。
   */
  override async mount(): Promise<void> {
    const target = this.root as HTMLElement & { noUiSlider?: NoUiSliderApi };
    if (target.noUiSlider) {
      this.slider = target.noUiSlider;
    } else {
      this.slider = noUiSlider.create(target, this.readOptions());
    }

    this.root.dataset.omSliderState = "ready";
    this.bindSliderEvent("update");
    this.bindSliderEvent("change");
    this.bindSliderEvent("slide");
    this.bindSliderEvent("set");
  }

  /**
   * 销毁 noUiSlider 实例，避免 Turbo 页面切换后残留事件和 DOM。
   */
  override async unmount(): Promise<void> {
    if (this.submitTimer !== null) {
      window.clearTimeout(this.submitTimer);
      this.submitTimer = null;
    }
    this.slider?.destroy();
    this.slider = null;
  }

  /**
   * 返回底层 noUiSlider API，供页面级 demo 编排使用。
   */
  instance(): NoUiSliderApi | null {
    return this.slider;
  }

  /**
   * 读取当前值。
   */
  get(unencoded = false): ReturnType<NoUiSliderApi["get"]> | null {
    return this.slider?.get(unencoded) ?? null;
  }

  /**
   * 设置当前值。
   */
  set(value: Parameters<NoUiSliderApi["set"]>[0]): void {
    this.slider?.set(value);
  }

  /**
   * 从 data 属性读取 noUiSlider 配置。
   */
  private readOptions(): NoUiSliderOptions {
    if (this.configuredOptions) return this.configuredOptions;

    const raw = this.root.getAttribute("data-om-slider-options");
    if (!raw) {
      throw new Error("Slider requires data-om-slider-options");
    }

    const options = JSON.parse(raw) as NoUiSliderOptions;
    const decimals = integerAttribute(this.root, "data-om-slider-format-decimals");
    if (decimals !== undefined) {
      options.format = wNumb({ decimals });
    }

    return options;
  }

  /**
   * 读取整数属性。
   */
  /**
   * 将 noUiSlider 事件转为 Oldman 自定义事件，便于页面和测试监听。
   */
  private bindSliderEvent(eventName: SliderEventName): void {
    this.slider?.on(eventName, (values, handle, _unencoded, _tap, positions) => {
      if (eventName === "update" || eventName === "change" || eventName === "set") {
        this.writeBoundInputs(values);
      }
      if (eventName === "change" || eventName === "set") {
        this.submitBoundForm();
      }
      this.emit<SliderEventDetail>(`om:slider:${eventName}`, {
        component: this,
        handle,
        positions,
        values
      });
    });
  }

  /**
   * 把 slider 当前值写入指定表单字段，供 table-filter-form 等外部组件读取。
   */
  private writeBoundInputs(values: Array<number | string>): void {
    const minName = this.root.getAttribute("data-om-slider-min-input");
    const maxName = this.root.getAttribute("data-om-slider-max-input");
    if (!minName && !maxName) return;

    const normalized = values.map((value) => this.normalizeValue(value));
    if (minName) this.writeInput(minName, normalized[0] ?? "");
    if (maxName) this.writeInput(maxName, normalized[1] ?? normalized[0] ?? "");
  }

  /**
   * 写入单个表单控件并派发 input/change，保持表单组件状态同步。
   */
  private writeInput(nameOrSelector: string, value: string): void {
    const input = this.resolveInput(nameOrSelector);
    if (!input) return;
    if (input.value === value) return;
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /**
   * 根据 name 或 CSS selector 找到绑定表单控件。
   */
  private resolveInput(nameOrSelector: string): HTMLInputElement | null {
    // 没有 form 时退回整个文档是刻意的：`data-om-slider-min-input` 是显式配置，
    // 表示"把值写到这个字段"，而滑块放在表单之外正是这条配置存在的理由。
    // 代价是同一页两个同名字段时会命中文档里的第一个；那是模板自己的歧义，
    // 框架收窄到 form 反而会挡掉无表单的用法。与 upload 的默认选择器不同——
    // 那里的全局兜底是意外的，这里是配置出来的。
    const form = this.resolveForm();
    const escaped = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(nameOrSelector) : nameOrSelector.replace(/"/g, '\\"');
    const byName = form?.querySelector<HTMLInputElement>(`[name="${escaped}"]`) ?? document.querySelector<HTMLInputElement>(`[name="${escaped}"]`);
    if (byName) return byName;
    try {
      return (form?.querySelector<HTMLInputElement>(nameOrSelector) ?? document.querySelector<HTMLInputElement>(nameOrSelector)) || null;
    } catch {
      return null;
    }
  }

  /**
   * 按配置找到需要提交的筛选表单。
   */
  private resolveForm(): HTMLFormElement | null {
    const selector = this.root.getAttribute("data-om-slider-form-selector");
    if (selector) {
      try {
        return document.querySelector<HTMLFormElement>(selector);
      } catch {
        return null;
      }
    }
    return this.root.closest("form");
  }

  /**
   * change/set 后按需提交绑定表单，和 table-filter-form 协议解耦。
   */
  private submitBoundForm(): void {
    if (this.root.getAttribute("data-om-slider-submit-on-change") !== "true") return;
    const form = this.resolveForm();
    if (!form) return;
    if (this.submitTimer !== null) window.clearTimeout(this.submitTimer);
    this.submitTimer = window.setTimeout(() => {
      this.submitTimer = null;
      form.requestSubmit();
    }, 0);
  }

  /**
   * 把 noUiSlider 的数字/格式化字符串规范成表单字段值。
   */
  private normalizeValue(value: number | string): string {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return String(Math.round(numeric));
    return String(value);
  }
}
