import { cssEscape } from "../core/dom/helpers";
import {
  ApiResponseAction,
  bindResponseOperationLifecycle,
  type DefaultApiFormResponse,
  showResponseActionFailure
} from "../core/actions/response-actions";
import { Component } from "../core/component/component";
import { isCanceledError } from "../core/services/abort";
import { getOldmanContext } from "../core/runtime/context";
import { bindPasswordVisibility } from "./form-password-visibility";

const FORM_SELECTOR = "[data-om-form]";
const FORM_MESSAGE_SELECTOR = "[data-om-form-message]";
const FORM_STATUS_SELECTOR = "[data-om-form-status]";
const FIELD_ERROR_SELECTOR = "[data-om-error-for]";
const FORM_INVALID = 1100;

export type FormErrors = Record<string, string>;
export type FormStatus = "idle" | "loading" | "success" | "error";
export type FormResponseMode = "json" | "html";

export interface FormSubmitSuccessDetail<TForm extends Form = Form> {
  component: TForm;
  form: HTMLFormElement;
  response: DefaultApiFormResponse;
  submitter?: HTMLElement;
}

export interface FormSubmitErrorDetail<TForm extends Form = Form> {
  component: TForm;
  form: HTMLFormElement;
  response?: DefaultApiFormResponse;
  error?: unknown;
  submitter?: HTMLElement;
}

/** Submit server-rendered forms through the current Page response-action pipeline. */
export class Form extends Component {
  static readonly componentName: string = "form";
  private readonly submittingForms = new WeakSet<HTMLFormElement>();

  override async mount(): Promise<void> {
    if (!this.page || this.manager !== this.page.components) {
      throw new Error("Form must be mounted by the current Page ComponentManager");
    }

    bindPasswordVisibility(this);
    this.on("submit", FORM_SELECTOR, (event, matchedElement) => {
      event.preventDefault();
      const form = matchedElement instanceof HTMLFormElement ? matchedElement : null;
      if (!form || !this.validateBeforeSubmit(form)) return;

      const submitter = event instanceof SubmitEvent ? event.submitter : null;
      void this.submitForm(form, submitter instanceof HTMLElement ? submitter : undefined);
    });
  }

  /** Submit one form and apply its normalized response exactly once. */
  async submitForm(form: HTMLFormElement, submitter?: HTMLElement): Promise<void> {
    if (this.submittingForms.has(form)) return;
    const page = this.page;
    if (!page) throw new Error("Form requires a mounted Page");

    const pageRegistry = getOldmanContext().pageRegistry;
    if (pageRegistry.current !== page || !pageContains(page, form)) {
      throw new Error("Form source must belong to the current mounted Page");
    }

    const controller = new AbortController();
    const cleanupOperation = bindResponseOperationLifecycle(controller, page, form);
    this.submittingForms.add(form);
    this.setStatus("loading", this.i18n.t("Saving..."), form);

    try {
      let response: DefaultApiFormResponse;
      try {
        response = await this.submitByMode(form, submitter, controller.signal);
      } catch (error) {
        if (controller.signal.aborted || isCanceledError(error)) return;
        this.setStatus("error", "", form);
        this.emitFormError(form, submitter, { error });
        await showResponseActionFailure(page, form, error);
        return;
      }

      if (
        controller.signal.aborted
        || pageRegistry.current !== page
        || !form.isConnected
        || !pageContains(page, form)
      ) return;

      this.clearFormResponse(form);
      this.renderMessage(form, response);
      this.showFormErrors(response.errors, form);

      try {
        await page.responseActions.run(response, form, controller.signal);
      } catch (error) {
        if (controller.signal.aborted || isCanceledError(error)) return;
        await showResponseActionFailure(page, form, error);
        return;
      }

      if (!form.isConnected) return;
      const success = response.error_code === 0 && Object.keys(response.errors).length === 0;
      this.setStatus(success ? "success" : "error", "", form);
      if (success) {
        this.emit<FormSubmitSuccessDetail>("om:form:success", {
          component: this,
          form,
          response,
          ...(submitter ? { submitter } : {})
        });
      } else {
        this.emitFormError(form, submitter, { response });
      }
    } finally {
      cleanupOperation();
      this.submittingForms.delete(form);
      if (form.isConnected && form.dataset.omStatus === "loading") this.setStatus("idle", "", form);
    }
  }

  /** Render concrete field errors; each field has one public error string. */
  showFormErrors(errors: FormErrors, scope: ParentNode = this.root): void {
    this.clearFormErrors(scope);
    for (const [name, message] of Object.entries(errors)) {
      for (const field of this.fieldsByName(name, scope)) field.setAttribute("aria-invalid", "true");
      for (const errorElement of this.errorElementsByName(name, scope)) {
        errorElement.textContent = message;
        errorElement.hidden = false;
      }
    }
  }

  /** Clear field error state inside this Form component. */
  clearFormErrors(scope: ParentNode = this.root): void {
    for (const field of scope.querySelectorAll<HTMLElement>("[aria-invalid='true']")) {
      field.removeAttribute("aria-invalid");
    }
    for (const errorElement of scope.querySelectorAll<HTMLElement>(FIELD_ERROR_SELECTOR)) {
      errorElement.textContent = "";
      errorElement.hidden = true;
    }
  }

  /** Update only the transient client-side submission status. */
  setStatus(status: FormStatus, message = "", scope: HTMLElement = this.root): void {
    scope.dataset.omStatus = status;
    const statusElement = scope.querySelector<HTMLElement>(FORM_STATUS_SELECTOR);
    if (!statusElement) return;
    statusElement.textContent = message;
    statusElement.hidden = status !== "loading" || message.length === 0;
  }

  private async submitByMode(
    form: HTMLFormElement,
    submitter: HTMLElement | undefined,
    signal: AbortSignal
  ): Promise<DefaultApiFormResponse> {
    if (this.formMode(form) === "json") {
      const result = await this.http.postForm<DefaultApiFormResponse>(
        this.formAction(form),
        form,
        {
          method: this.formMethod(form),
          headers: { Accept: "application/json" },
          signal
        },
        submitter
      );
      return result.data;
    }

    const result = await this.http.postForm<string>(
      this.formAction(form),
      form,
      {
        method: this.formMethod(form),
        headers: { Accept: "text/html" },
        responseType: "text",
        signal,
        validateStatus: (status) => status === 422 || (status >= 200 && status < 300)
      },
      submitter
    );
    return {
      error_code: result.status === 422 ? FORM_INVALID : 0,
      message: "",
      data: {},
      errors: {},
      actions: [{ action: ApiResponseAction.REPLACE_HTML, html: result.data }]
    };
  }

  private clearFormResponse(form: HTMLFormElement): void {
    this.clearFormErrors(form);
    const message = form.querySelector<HTMLElement>(FORM_MESSAGE_SELECTOR);
    if (!message) return;
    message.textContent = "";
    message.hidden = true;
    message.removeAttribute("role");
    message.removeAttribute("aria-live");
    message.removeAttribute("data-om-tone");
  }

  private renderMessage(form: HTMLFormElement, response: DefaultApiFormResponse): void {
    if (!response.message) return;
    const success = response.error_code === 0 && Object.keys(response.errors).length === 0;
    this.showMessage(form, response.message, success);
  }

  private showMessage(form: HTMLFormElement, text: string, success: boolean): void {
    const message = form.querySelector<HTMLElement>(FORM_MESSAGE_SELECTOR);
    if (!message) return;
    message.textContent = text;
    message.hidden = false;
    message.dataset.omTone = success ? "success" : "error";
    message.setAttribute("role", success ? "status" : "alert");
    if (success) message.setAttribute("aria-live", "polite");
  }

  private emitFormError(
    form: HTMLFormElement,
    submitter: HTMLElement | undefined,
    result: { response?: DefaultApiFormResponse; error?: unknown }
  ): void {
    this.emit<FormSubmitErrorDetail>("om:form:error", {
      component: this,
      form,
      ...result,
      ...(submitter ? { submitter } : {})
    });
  }

  private fieldsByName(name: string, scope: ParentNode): HTMLElement[] {
    return Array.from(scope.querySelectorAll<HTMLElement>(`[name="${cssEscape(name)}"]`));
  }

  private errorElementsByName(name: string, scope: ParentNode): HTMLElement[] {
    return Array.from(scope.querySelectorAll<HTMLElement>(`[data-om-error-for="${cssEscape(name)}"]`));
  }

  private formAction(form: HTMLFormElement): string {
    return form.getAttribute("action") || window.location.href;
  }

  private formMethod(form: HTMLFormElement): string {
    return form.getAttribute("method") || "post";
  }

  private formMode(form: HTMLFormElement): FormResponseMode {
    const mode = form.getAttribute("data-om-form-mode") || this.root.getAttribute("data-om-form-mode");
    return mode === "json" ? "json" : "html";
  }

  private validateBeforeSubmit(form: HTMLFormElement): boolean {
    if (!this.shouldValidate(form)) return true;
    const valid = form.checkValidity();
    form.classList.add(form.getAttribute("data-om-form-validation-class") || "was-validated");
    if (!valid) {
      const invalidFields = Array.from(
        form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
          "input:invalid, select:invalid, textarea:invalid"
        )
      );
      const errors: FormErrors = {};
      for (const field of invalidFields) {
        if (field.name && !(field.name in errors)) errors[field.name] = field.validationMessage;
      }
      this.clearFormResponse(form);
      this.showFormErrors(errors, form);
      this.showMessage(form, this.i18n.t("Form validation failed"), false);
      this.setStatus("error", "", form);
      invalidFields[0]?.focus();
    }
    return valid;
  }

  private shouldValidate(form: HTMLFormElement): boolean {
    return form.hasAttribute("data-om-form-validate") || this.root.hasAttribute("data-om-form-validate");
  }
}

function pageContains(page: { root: HTMLElement }, source: HTMLElement): boolean {
  return page.root !== source && page.root.contains(source);
}
