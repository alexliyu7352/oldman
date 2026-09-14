import { Component, type ComponentOptions } from "../core/component/component";

const DEFAULT_VALIDATED_CLASS = "was-validated";

export interface FormValidatorDetail<TComponent extends FormValidator = FormValidator> {
  component: TComponent;
  form: HTMLFormElement;
}

export interface FormValidatorInvalidDetail<TComponent extends FormValidator = FormValidator>
  extends FormValidatorDetail<TComponent> {
  controls: HTMLElement[];
}

export interface FormValidatorOptions extends ComponentOptions {
  validatedClass?: string;
}

/**
 * 提供基于浏览器 Constraint Validation API 的表单校验生命周期。
 */
export class FormValidator extends Component {
  static readonly componentName = "form-validator";
  private readonly configuredValidatedClass: string;

  /**
   * 创建表单校验组件，允许不同主题覆盖校验完成后的状态 class。
   */
  constructor(root: HTMLElement, options: FormValidatorOptions = {}) {
    super(root, options);
    this.configuredValidatedClass = options.validatedClass ?? "";
  }

  /**
   * 绑定 submit 和 reset 事件，替代模板自带的表单校验初始化脚本。
   */
  override async mount(): Promise<void> {
    const form = this.formElement();
    if (!form) return;

    this.listen(form, "submit", (event) => {
      this.validate(event);
    });
    this.listen(form, "reset", () => {
      this.reset();
    });
  }

  /**
   * 执行原生校验；无效时阻止提交并派发 invalid 事件。
   */
  validate(event?: Event): boolean {
    const form = this.formElement();
    if (!form) return true;

    return this.validateControls(form, Array.from(form.elements), event);
  }

  /** 校验表单中的一个字段分组，供多步骤表单前进前复用。 */
  validateScope(scope: HTMLElement, event?: Event): boolean {
    const form = this.formElement();
    if (!form) return true;

    return this.validateControls(
      form,
      Array.from(form.elements).filter((element) => element instanceof HTMLElement && scope.contains(element)),
      event
    );
  }

  private validateControls(form: HTMLFormElement, controls: Element[], event?: Event): boolean {
    const invalidControls = this.invalidControls(controls);
    const valid = invalidControls.length === 0;
    if (!valid) {
      event?.preventDefault();
      event?.stopPropagation();
    }

    form.classList.add(this.validatedClass());
    if (valid) {
      this.emit<FormValidatorDetail>("om:form-validator:valid", { component: this, form });
    } else {
      this.emit<FormValidatorInvalidDetail>("om:form-validator:invalid", {
        component: this,
        controls: invalidControls,
        form
      });
    }

    return valid;
  }

  /**
   * 清理校验状态 class，通常用于表单 reset 或页面复用。
   */
  reset(): void {
    const form = this.formElement();
    if (!form) return;

    form.classList.remove(this.validatedClass());
    this.emit<FormValidatorDetail>("om:form-validator:reset", { component: this, form });
  }

  /**
   * 返回组件根节点对应的表单，支持直接挂在 form 或外层容器上。
   */
  private formElement(): HTMLFormElement | null {
    if (this.root instanceof HTMLFormElement) return this.root;
    return this.root.querySelector("form") ?? this.root.closest("form");
  }

  /**
   * 返回当前主题使用的校验状态 class。
   */
  private validatedClass(): string {
    return this.root.getAttribute("data-om-form-validation-class") || this.configuredValidatedClass || DEFAULT_VALIDATED_CLASS;
  }

  /**
   * 收集当前未通过原生校验的控件，供业务层聚焦或展示摘要。
   */
  private invalidControls(controls: Element[]): HTMLElement[] {
    return controls.filter((element): element is HTMLElement => {
      return element instanceof HTMLElement && "checkValidity" in element && !(element as HTMLInputElement).checkValidity();
    });
  }
}
