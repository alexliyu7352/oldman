import Cleave from "cleave.js";
import { Component, type ComponentOptions } from "../core/component/component";

export type CleaveDatePattern = "d" | "m" | "Y" | "y";
export type CleaveTimePattern = "h" | "m" | "s";
export type CleaveNumeralThousandsGroupStyle = "thousand" | "lakh" | "wan" | "none";

/** Public, dependency-independent subset of Cleave options supported by FormMask. */
export interface CleaveOptions {
  blocks?: number[];
  date?: boolean;
  datePattern?: CleaveDatePattern[];
  delimiter?: string;
  delimiters?: string[];
  numeral?: boolean;
  numeralThousandsGroupStyle?: CleaveNumeralThousandsGroupStyle;
  prefix?: string;
  time?: boolean;
  timePattern?: CleaveTimePattern[];
  uppercase?: boolean;
}

export type FormMaskType =
  | "credit-card"
  | "date"
  | "date-month"
  | "delimiter"
  | "delimiters"
  | "numeral"
  | "phone"
  | "prefix"
  | "time"
  | "time-short";

export interface FormMaskOptions extends ComponentOptions {
  maskOptions?: CleaveOptions;
  maskType?: FormMaskType;
}

export interface FormMaskDetail<TComponent extends FormMask = FormMask> {
  component: TComponent;
  input: HTMLInputElement;
  rawValue: string;
  value: string;
}

/**
 * 基于 Cleave 的无头输入掩码组件，负责格式化输入值并管理第三方实例生命周期。
 */
export class FormMask extends Component {
  static readonly componentName = "form-mask";
  private readonly configuredMaskOptions: CleaveOptions | undefined;
  private readonly configuredMaskType: FormMaskType | undefined;
  private instance: Cleave | null = null;

  /**
   * 创建输入掩码组件，可通过构造参数或 data 属性声明格式化规则。
   */
  constructor(root: HTMLElement, options: FormMaskOptions = {}) {
    super(root, options);
    this.configuredMaskOptions = options.maskOptions;
    this.configuredMaskType = options.maskType;
  }

  /**
   * 初始化 Cleave 实例，并监听输入变化派发标准事件。
   */
  override async mount(): Promise<void> {
    const input = this.inputElement();
    if (!input) return;

    this.instance = new Cleave(input, this.resolveOptions(input));
    this.listen(input, "input", () => {
      this.emit<FormMaskDetail>("om:form-mask:change", {
        component: this,
        input,
        rawValue: this.rawValue(),
        value: input.value
      });
    });
  }

  /**
   * 销毁 Cleave 实例，避免 Turbo 页面切换后遗留事件监听。
   */
  override async unmount(): Promise<void> {
    this.instance?.destroy();
    this.instance = null;
  }

  /**
   * 返回去掉分隔符和前缀后的原始值。
   */
  rawValue(): string {
    return this.instance?.getRawValue() ?? this.inputElement()?.value ?? "";
  }

  /**
   * 写入原始值并让 Cleave 重新渲染格式化结果。
   */
  setRawValue(value: string): void {
    if (this.instance) {
      this.instance.setRawValue(value);
      return;
    }

    const input = this.inputElement();
    if (input) input.value = value;
  }

  /**
   * 查找当前组件管理的输入框。
   */
  private inputElement(): HTMLInputElement | null {
    if (this.root instanceof HTMLInputElement) return this.root;
    return this.root.querySelector<HTMLInputElement>("input");
  }

  /**
   * 合并预设、JSON 配置和细粒度 data 属性。
   */
  private resolveOptions(input: HTMLInputElement): CleaveOptions {
    return {
      ...this.presetOptions(this.maskType(input)),
      ...this.jsonOptions(input),
      ...this.attributeOptions(input),
      ...this.configuredMaskOptions
    };
  }

  /**
   * 返回声明的预设类型。
   */
  private maskType(input: HTMLInputElement): FormMaskType | undefined {
    return this.configuredMaskType ?? (this.readAttribute(input, "data-om-mask-type") as FormMaskType | null) ?? undefined;
  }

  /**
   * 按常用业务场景返回 Cleave 配置预设。
   */
  private presetOptions(type: FormMaskType | undefined): CleaveOptions {
    switch (type) {
      case "credit-card":
        return { blocks: [4, 4, 4, 4], uppercase: true };
      case "date":
        return { date: true, datePattern: ["d", "m", "Y"], delimiter: "-" };
      case "date-month":
        return { date: true, datePattern: ["m", "y"] };
      case "delimiter":
        return { blocks: [3, 3, 3], delimiter: "·", uppercase: true };
      case "delimiters":
        return { blocks: [3, 3, 3, 2], delimiters: [".", ".", "-"], uppercase: true };
      case "numeral":
        return { numeral: true, numeralThousandsGroupStyle: "thousand" };
      case "phone":
        return { blocks: [0, 3, 3, 4], delimiters: ["(", ")", "-"] };
      case "prefix":
        return { blocks: [6, 4, 4, 4], delimiter: "-", prefix: "PREFIX", uppercase: true };
      case "time":
        return { time: true, timePattern: ["h", "m", "s"] };
      case "time-short":
        return { time: true, timePattern: ["h", "m"] };
      default:
        return {};
    }
  }

  /**
   * 读取 JSON 配置，支持页面对 Cleave 参数做完整覆盖。
   */
  private jsonOptions(input: HTMLInputElement): CleaveOptions {
    const rawValue = this.readAttribute(input, "data-om-mask-options");
    if (!rawValue) return {};

    try {
      return JSON.parse(rawValue) as CleaveOptions;
    } catch {
      return {};
    }
  }

  /**
   * 读取常用的细粒度 data 属性。
   */
  private attributeOptions(input: HTMLInputElement): CleaveOptions {
    const options: CleaveOptions = {};
    const delimiter = this.readAttribute(input, "data-om-mask-delimiter");
    const prefix = this.readAttribute(input, "data-om-mask-prefix");
    const blocks = this.readNumberList(input, "data-om-mask-blocks");
    const delimiters = this.readStringList(input, "data-om-mask-delimiters");
    const datePattern = this.readDatePattern(input);
    const timePattern = this.readTimePattern(input);

    if (delimiter !== null) options.delimiter = delimiter;
    if (prefix !== null) options.prefix = prefix;
    if (blocks.length > 0) options.blocks = blocks;
    if (delimiters.length > 0) options.delimiters = delimiters;
    if (datePattern.length > 0) {
      options.date = true;
      options.datePattern = datePattern;
    }
    if (timePattern.length > 0) {
      options.time = true;
      options.timePattern = timePattern;
    }
    if (this.hasAttribute(input, "data-om-mask-uppercase")) options.uppercase = true;
    if (this.hasAttribute(input, "data-om-mask-numeral")) options.numeral = true;
    if (this.hasAttribute(input, "data-om-mask-date")) options.date = true;
    if (this.hasAttribute(input, "data-om-mask-time")) options.time = true;

    return options;
  }

  /**
   * 从组件根节点或输入框读取属性值。
   */
  private readAttribute(input: HTMLInputElement, name: string): string | null {
    return this.root.getAttribute(name) ?? input.getAttribute(name);
  }

  /**
   * 判断组件根节点或输入框是否声明了布尔属性。
   */
  private hasAttribute(input: HTMLInputElement, name: string): boolean {
    return this.root.hasAttribute(name) || input.hasAttribute(name);
  }

  /**
   * 读取数字列表，兼容 JSON 数组和逗号分隔写法。
   */
  private readNumberList(input: HTMLInputElement, name: string): number[] {
    return this.readStringList(input, name)
      .map((item) => Number(item))
      .filter((item) => Number.isFinite(item));
  }

  /**
   * 读取字符串列表，兼容 JSON 数组和逗号分隔写法。
   */
  private readStringList(input: HTMLInputElement, name: string): string[] {
    const value = this.readAttribute(input, name);
    if (!value) return [];

    try {
      const parsed = JSON.parse(value) as unknown;
      if (Array.isArray(parsed)) return parsed.map((item) => String(item));
    } catch {
      // 非 JSON 时回退到逗号分隔写法。
    }

    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }

  /**
   * 读取并过滤 Cleave 支持的日期 pattern。
   */
  private readDatePattern(input: HTMLInputElement): CleaveDatePattern[] {
    const allowed = new Set<CleaveDatePattern>(["d", "m", "Y", "y"]);
    return this.readStringList(input, "data-om-mask-date-pattern").filter((item): item is CleaveDatePattern => {
      return allowed.has(item as CleaveDatePattern);
    });
  }

  /**
   * 读取并过滤 Cleave 支持的时间 pattern。
   */
  private readTimePattern(input: HTMLInputElement): CleaveTimePattern[] {
    const allowed = new Set<CleaveTimePattern>(["h", "m", "s"]);
    return this.readStringList(input, "data-om-mask-time-pattern").filter((item): item is CleaveTimePattern => {
      return allowed.has(item as CleaveTimePattern);
    });
  }
}
