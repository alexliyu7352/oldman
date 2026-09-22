import flatpickr from "flatpickr";
import "./date-time-picker.scss";
import { Component } from "../core/component/component";

type FlatpickrOptions = Partial<flatpickr.Options.Options>;
type FlatpickrInstance = flatpickr.Instance;

/**
 * 基于 flatpickr 的无头日期/时间选择组件，兼容 data-provider 声明。
 */
export class DateTimePicker extends Component {
  static readonly componentName = "date-time-picker";
  private instance: FlatpickrInstance | null = null;

  /**
   * 根据 data-provider 初始化日期或时间选择器。
   */
  override async mount(): Promise<void> {
    const input = this.input();
    if (!input) return;

    const options = input.getAttribute("data-provider") === "timepickr" ? this.readTimeOptions(input) : this.readDateOptions(input);
    this.instance = flatpickr(input, options) as FlatpickrInstance;
  }

  /**
   * 销毁 flatpickr 实例，避免页面切换后遗留弹层和事件。
   */
  override async unmount(): Promise<void> {
    if (!this.instance) return;

    this.instance.destroy();
    this.instance = null;
  }

  /**
   * 返回组件根节点管理的输入框。
   */
  private input(): HTMLInputElement | null {
    if (this.root instanceof HTMLInputElement) return this.root;
    return this.root.querySelector<HTMLInputElement>('[data-provider="flatpickr"], [data-provider="timepickr"]');
  }

  /**
   * 将 flatpickr 日期类 data 属性转换为标准配置。
   */
  private readDateOptions(input: HTMLInputElement): FlatpickrOptions {
    const options: FlatpickrOptions = { disableMobile: true };
    const dateFormat = input.getAttribute("data-date-format");

    if (dateFormat) options.dateFormat = dateFormat;
    if (input.hasAttribute("data-enable-time")) {
      options.enableTime = true;
      options.dateFormat = dateFormat ? this.dateFormatWithTime(dateFormat) : "Y-m-d H:i";
    }
    if (input.hasAttribute("data-altFormat")) {
      options.altInput = true;
      this.assignStringOption(options, "altFormat", input.getAttribute("data-altFormat"));
    }
    if (input.hasAttribute("data-minDate")) {
      this.assignStringOption(options, "minDate", input.getAttribute("data-minDate"));
      if (dateFormat) options.dateFormat = dateFormat;
    }
    if (input.hasAttribute("data-maxDate")) {
      this.assignStringOption(options, "maxDate", input.getAttribute("data-maxDate"));
      if (dateFormat) options.dateFormat = dateFormat;
    }
    const defaultDate = this.defaultDateAttribute(input);
    if (defaultDate !== null) {
      this.assignStringOption(options, "defaultDate", defaultDate);
      if (dateFormat) options.dateFormat = dateFormat;
    }
    if (input.hasAttribute("data-multiple-date")) {
      options.mode = "multiple";
      if (dateFormat) options.dateFormat = dateFormat;
    }
    if (input.hasAttribute("data-range-date")) {
      options.mode = "range";
      if (dateFormat) options.dateFormat = dateFormat;
    }
    if (input.hasAttribute("data-inline-date")) {
      options.inline = true;
      this.assignStringOption(options, "defaultDate", this.defaultDateAttribute(input));
      if (dateFormat) options.dateFormat = dateFormat;
    }
    if (input.hasAttribute("data-disable-date")) {
      options.disable = (input.getAttribute("data-disable-date") ?? "").split(",");
    }
    if (input.hasAttribute("data-week-number")) {
      options.weekNumbers = true;
    }

    return options;
  }

  /**
   * 将 timepickr 时间类 data 属性转换为 flatpickr 时间模式配置。
   */
  private readTimeOptions(input: HTMLInputElement): FlatpickrOptions {
    const options: FlatpickrOptions = {};

    if (input.hasAttribute("data-time-basic") || input.hasAttribute("data-time-hrs")) {
      this.applyTimeOnlyDefaults(options);
    }
    if (input.hasAttribute("data-time-hrs")) {
      options.time_24hr = true;
    }
    if (input.hasAttribute("data-min-time")) {
      this.applyTimeOnlyDefaults(options);
      this.assignStringOption(options, "minTime", input.getAttribute("data-min-time"));
    }
    if (input.hasAttribute("data-max-time")) {
      this.applyTimeOnlyDefaults(options);
      this.assignStringOption(options, "maxTime", input.getAttribute("data-max-time"));
    }
    if (input.hasAttribute("data-default-time")) {
      this.applyTimeOnlyDefaults(options);
      this.assignStringOption(options, "defaultDate", input.getAttribute("data-default-time"));
    }
    if (input.hasAttribute("data-time-inline")) {
      this.applyTimeOnlyDefaults(options);
      this.assignStringOption(options, "defaultDate", input.getAttribute("data-time-inline"));
      options.inline = true;
    }

    return options;
  }

  /**
   * 应用时间选择器的基础配置。
   */
  private applyTimeOnlyDefaults(options: FlatpickrOptions): void {
    options.enableTime = true;
    options.noCalendar = true;
    options.dateFormat = "H:i";
  }

  /**
   * 纯日期格式启用时间时才追加时间；后端显式 datetime 格式必须原样保留。
   */
  private dateFormatWithTime(dateFormat: string): string {
    return /[HhGiS]/.test(dateFormat) ? dateFormat : `${dateFormat} H:i`;
  }

  /**
   * 读取默认日期，两种拼写都认。
   *
   * 实现里一直写的是 `data-deafult-date`（`deafult`），而且这个文件的测试用的也是错拼写，
   * 所以它一直是绿的——等于把打错的名字变成了既成契约。正确拼写现在优先，旧名字继续支持：
   * 直接改掉会打断已经按错拼写写好模板的使用者。
   */
  private defaultDateAttribute(input: HTMLInputElement): string | null {
    return input.getAttribute("data-default-date") ?? input.getAttribute("data-deafult-date");
  }

  /**
   * 设置可选字符串配置，避免显式写入 undefined。
   */
  private assignStringOption<TKey extends keyof FlatpickrOptions>(
    options: FlatpickrOptions,
    key: TKey,
    value: string | null
  ): void {
    if (value !== null) {
      (options as Record<TKey, string>)[key] = value;
    }
  }
}
