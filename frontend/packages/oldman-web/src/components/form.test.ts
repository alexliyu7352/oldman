import { afterEach, describe, expect, it, vi } from "vitest";
import type { HttpClient } from "../core/http/client";
import { Page } from "../core/page/page";
import { PageRegistry } from "../core/page/registry";
import { createOldmanContext, resetOldmanContext, setOldmanContext } from "../core/runtime/context";
import { Form } from "./form";

class FormTestPage extends Page {
  static readonly pageName = "form-test";
  readonly privateActions: string[] = [];

  override async mount(): Promise<void> {
    this.components.register(Form);
    await this.components.mount(this.root);
  }

  override async handleResponseAction(action: { action: string }): Promise<boolean> {
    if (action.action !== "private") return false;
    this.privateActions.push(action.action);
    return true;
  }
}

let registry: PageRegistry | null = null;

afterEach(async () => {
  await registry?.unmount();
  registry = null;
  resetOldmanContext();
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("Form", () => {
  it("requires the current Page ComponentManager", async () => {
    const root = document.createElement("form");
    root.dataset.omForm = "";
    document.body.append(root);

    await expect(new Form(root).start()).rejects.toThrow(
      "Form must be mounted by the current Page ComponentManager"
    );
  });

  it("keeps password visibility on the ordinary Form component", async () => {
    const { form } = await mountForm(
      '<form data-om-component="form" data-om-form>'
      + '<input id="account-password" name="password" type="password" value="secret">'
      + '<button type="button" aria-controls="account-password" data-om-password-toggle '
      + 'data-om-label-show="Show password" data-om-label-hide="Hide password"></button></form>'
    );
    const input = form.querySelector<HTMLInputElement>("input")!;
    const toggle = form.querySelector<HTMLButtonElement>("button")!;

    toggle.click();
    expect(input.type).toBe("text");
    expect(input.value).toBe("secret");
    expect(toggle.getAttribute("aria-label")).toBe("Hide password");
  });

  it("defaults to HTML and converts a successful fragment into one replace action", async () => {
    const http = createHttp();
    vi.mocked(http.postForm).mockResolvedValue({
      data: '<form data-om-component="form" data-om-form data-revision="2" action="/profile/updated">'
        + '<div data-om-form-message hidden></div><input name="display_name" value="new">'
        + '<p data-om-form-status hidden></p></form>',
      status: 200
    });
    const { component, form } = await mountForm(
      '<form data-om-component="form" data-om-form action="/profile" method="post">'
      + '<div data-om-form-message hidden></div><input name="display_name" value="old">'
      + '<p data-om-form-status hidden></p></form>',
      http
    );
    const success = vi.fn();
    form.addEventListener("om:form:success", success);

    await component.submitForm(form);

    expect(http.postForm).toHaveBeenCalledWith(
      "/profile",
      form,
      expect.objectContaining({
        method: "post",
        headers: { Accept: "text/html" },
        responseType: "text",
        signal: expect.any(AbortSignal),
        validateStatus: expect.any(Function)
      }),
      undefined
    );
    expect(form.getAttribute("action")).toBe("/profile/updated");
    expect(form.dataset.revision).toBe("2");
    expect(form.querySelector<HTMLInputElement>("[name='display_name']")?.value).toBe("new");
    expect(success).toHaveBeenCalledOnce();
    expect((success.mock.calls[0]?.[0] as CustomEvent).detail.response.error_code).toBe(0);
  });

  it("treats HTML 422 as a rendered business error without a network failure", async () => {
    const http = createHttp();
    vi.mocked(http.postForm).mockResolvedValue({
      data: '<form data-om-component="form" data-om-form action="/profile">'
        + '<div data-om-form-message role="alert" data-om-tone="error">Form validation failed</div>'
        + '<input name="email" value="bad" aria-invalid="true">'
        + '<p data-om-error-for="email">Email is invalid</p><p data-om-form-status hidden></p></form>',
      status: 422
    });
    const { component, form, page } = await mountForm(
      '<form data-om-component="form" data-om-form action="/profile">'
      + '<div data-om-form-message hidden></div><input name="email" value="bad">'
      + '<p data-om-error-for="email" hidden></p><p data-om-form-status hidden></p></form>',
      http
    );
    const failed = vi.fn();
    form.addEventListener("om:form:error", failed);
    const alert = vi.fn().mockResolvedValue({});
    page.feedback = { alert, toast: vi.fn(), close: vi.fn() };

    await component.submitForm(form);

    expect(form.querySelector("[aria-invalid='true']")).not.toBeNull();
    expect(form.querySelector("[data-om-form-message]")?.textContent).toBe("Form validation failed");
    expect(failed).toHaveBeenCalledOnce();
    expect((failed.mock.calls[0]?.[0] as CustomEvent).detail.response.error_code).toBe(1100);
    expect((failed.mock.calls[0]?.[0] as CustomEvent).detail.error).toBeUndefined();
    expect(alert).not.toHaveBeenCalled();
  });

  it.each(["html", "json"])("shows one shared request failure for %s Form without a business message", async (mode) => {
    const http = createHttp();
    const error = new Error("Network Error");
    vi.mocked(http.postForm).mockRejectedValue(error);
    const { component, form, page } = await mountForm(
      `<form data-om-component="form" data-om-form data-om-form-mode="${mode}" action="/profile">`
      + '<div data-om-form-message hidden></div><p data-om-form-status hidden></p></form>',
      http
    );
    const alert = vi.fn().mockResolvedValue({});
    page.feedback = { alert, toast: vi.fn(), close: vi.fn() };
    const failed = vi.fn();
    const success = vi.fn();
    form.addEventListener("om:form:error", failed);
    form.addEventListener("om:form:success", success);

    await component.submitForm(form);

    expect(alert).toHaveBeenCalledOnce();
    expect(alert).toHaveBeenCalledWith({ icon: "error", titleText: "Request failed" });
    expect(failed).toHaveBeenCalledOnce();
    expect((failed.mock.calls[0]?.[0] as CustomEvent).detail.error).toBe(error);
    expect(success).not.toHaveBeenCalled();
    expect(form.dataset.omStatus).toBe("error");
    expect(form.querySelector<HTMLElement>("[data-om-form-status]")?.hidden).toBe(true);
    expect(form.querySelector<HTMLElement>("[data-om-form-message]")?.hidden).toBe(true);
  });

  it("renders JSON message and errors before running business-error actions", async () => {
    const http = createHttp();
    vi.mocked(http.postForm).mockResolvedValue({
      data: {
        error_code: 1100,
        message: "<b>Form validation failed</b>",
        data: {},
        errors: { email: "Email is invalid" },
        actions: [{ action: "replace_html", target: "#summary", html: "<strong>invalid</strong>" }]
      },
      status: 200
    });
    const { component, form } = await mountForm(
      '<form data-om-component="form" data-om-form data-om-form-mode="json" action="/profile">'
      + '<div data-om-form-message hidden></div><input name="email" value="bad">'
      + '<p data-om-error-for="email" hidden></p><p data-om-form-status hidden></p></form>'
      + '<div id="summary">old</div>',
      http
    );
    const failed = vi.fn();
    form.addEventListener("om:form:error", failed);

    await component.submitForm(form);

    const message = form.querySelector<HTMLElement>("[data-om-form-message]")!;
    expect(message.textContent).toBe("<b>Form validation failed</b>");
    expect(message.querySelector("b")).toBeNull();
    expect(message.dataset.omTone).toBe("error");
    expect(message.getAttribute("role")).toBe("alert");
    expect(form.querySelector("[data-om-error-for='email']")?.textContent).toBe("Email is invalid");
    expect(document.querySelector("#summary")?.innerHTML).toBe("<strong>invalid</strong>");
    expect(failed).toHaveBeenCalledOnce();
  });

  it("continues later actions after an outer replace removes the source Form", async () => {
    const http = createHttp();
    vi.mocked(http.postForm).mockResolvedValue({
      data: {
        error_code: 0,
        message: "",
        data: {},
        errors: {},
        actions: [
          { action: "replace_html", target: "#profile", swap: "outer", html: "<p id='profile'>saved</p>" },
          { action: "private" }
        ]
      },
      status: 200
    });
    const { component, form, page } = await mountForm(
      '<form id="profile" data-om-component="form" data-om-form data-om-form-mode="json" action="/profile">'
      + '<p data-om-form-status hidden></p></form>',
      http
    );
    const success = vi.fn();
    form.addEventListener("om:form:success", success);

    await component.submitForm(form);

    expect(document.querySelector("#profile")?.textContent).toBe("saved");
    expect(page.privateActions).toEqual(["private"]);
    expect(success).not.toHaveBeenCalled();
  });

  it("stops on an action failure without emitting a Form status event", async () => {
    const http = createHttp();
    vi.mocked(http.postForm).mockResolvedValue({
      data: {
        error_code: 0,
        message: "",
        data: {},
        errors: {},
        actions: [{ action: "unknown" }, { action: "private" }]
      },
      status: 200
    });
    const { component, form, page } = await mountForm(
      '<form data-om-component="form" data-om-form data-om-form-mode="json" action="/profile">'
      + '<p data-om-form-status hidden></p></form>',
      http
    );
    const alert = vi.fn().mockResolvedValue({});
    page.feedback = { alert, toast: vi.fn(), close: vi.fn() };
    const success = vi.fn();
    const failed = vi.fn();
    form.addEventListener("om:form:success", success);
    form.addEventListener("om:form:error", failed);

    await component.submitForm(form);

    expect(alert).toHaveBeenCalledWith({ icon: "error", titleText: "Request failed" });
    expect(page.privateActions).toEqual([]);
    expect(success).not.toHaveBeenCalled();
    expect(failed).not.toHaveBeenCalled();
  });

  it.each(["turbo:before-fetch-request", "turbo:before-frame-render"])(
    "cancels on source Turbo Frame %s and restores loading",
    async (eventName) => {
    const http = createHttp();
    vi.mocked(http.postForm).mockImplementation((_url, _form, config) => new Promise((_resolve, reject) => {
      (config?.signal as AbortSignal | undefined)?.addEventListener(
        "abort",
        () => reject(new DOMException("Aborted", "AbortError")),
        { once: true }
      );
    }));
    const { component, form, page } = await mountForm(
      '<turbo-frame id="main"><form data-om-component="form" data-om-form action="/profile">'
      + '<p data-om-form-status hidden></p></form></turbo-frame>',
      http
    );
    const success = vi.fn();
    const failed = vi.fn();
    const alert = vi.fn().mockResolvedValue({});
    page.feedback = { alert, toast: vi.fn(), close: vi.fn() };
    form.addEventListener("om:form:success", success);
    form.addEventListener("om:form:error", failed);

    const pending = component.submitForm(form);
    form.closest("turbo-frame")!.dispatchEvent(new CustomEvent(eventName));
    await pending;

    expect(form.dataset.omStatus).toBe("idle");
    expect(form.querySelector<HTMLElement>("[data-om-form-status]")?.hidden).toBe(true);
    expect(success).not.toHaveBeenCalled();
    expect(failed).not.toHaveBeenCalled();
    expect(alert).not.toHaveBeenCalled();
    }
  );

  it("ignores other Frames and removes operation listeners after completion", async () => {
    const http = createHttp();
    const pendingResponse = deferred<{ data: string; status: number }>();
    let operationSignal: AbortSignal | undefined;
    vi.mocked(http.postForm).mockImplementation((_url, _form, config) => {
      operationSignal = config?.signal as AbortSignal | undefined;
      return pendingResponse.promise;
    });
    const { component, form } = await mountForm(
      '<turbo-frame id="main"><form data-om-component="form" data-om-form action="/profile">'
      + '<p data-om-form-status hidden></p></form></turbo-frame><turbo-frame id="other"></turbo-frame>',
      http
    );

    const pending = component.submitForm(form);
    document.querySelector("#other")!.dispatchEvent(new CustomEvent("turbo:before-frame-render"));
    expect(operationSignal?.aborted).toBe(false);
    pendingResponse.resolve({
      data: '<form data-om-component="form" data-om-form action="/profile"><p data-om-form-status hidden></p></form>',
      status: 200
    });
    await pending;

    form.closest("turbo-frame")!.dispatchEvent(new CustomEvent("turbo:before-frame-render"));
    expect(operationSignal?.aborted).toBe(false);
  });

  it("uses native constraint validation before sending a request", async () => {
    const http = createHttp();
    const { form } = await mountForm(
      '<form data-om-component="form" data-om-form data-om-form-validate action="/profile">'
      + '<div data-om-form-message hidden></div>'
      + '<input name="email" type="email" value="bad">'
      + '<p data-om-error-for="email" hidden></p><p data-om-form-status hidden></p></form>',
      http
    );
    const email = form.elements.namedItem("email") as HTMLInputElement;

    form.dispatchEvent(new SubmitEvent("submit", { bubbles: true, cancelable: true }));

    expect(http.postForm).not.toHaveBeenCalled();
    expect(form.classList.contains("was-validated")).toBe(true);
    expect(form.dataset.omStatus).toBe("error");
    expect(email.getAttribute("aria-invalid")).toBe("true");
    expect(form.querySelector<HTMLElement>("[data-om-error-for='email']")?.textContent).toBe(
      email.validationMessage
    );
    expect(form.querySelector<HTMLElement>("[data-om-error-for='email']")?.hidden).toBe(false);
    expect(form.querySelector<HTMLElement>("[data-om-form-message]")?.textContent).toBe(
      "Form validation failed"
    );
    expect(document.activeElement).toBe(email);
  });
});

async function mountForm(markup: string, http = createHttp()) {
  document.body.innerHTML = '<main data-om-page="form-test">' + markup + "</main>";
  registry = new PageRegistry();
  setOldmanContext(createOldmanContext({ http, pageRegistry: registry }));
  registry.register(FormTestPage);
  const page = await registry.mount(document) as FormTestPage;
  const form = page.root.querySelector<HTMLFormElement>("[data-om-form]")!;
  const componentRoot = form.closest<HTMLElement>("[data-om-component='form']")!;
  const component = page.components.get<Form>(componentRoot)!;
  return { component, form, http, page };
}

function createHttp(): HttpClient {
  return {
    axios: {} as HttpClient["axios"],
    getJson: vi.fn(),
    postJson: vi.fn(),
    html: vi.fn(),
    postForm: vi.fn()
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}
