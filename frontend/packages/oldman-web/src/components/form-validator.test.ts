import { describe, expect, it } from "vitest";
import { FormValidator } from "./form-validator";

describe("FormValidator", () => {
  it("无效提交时阻止提交、写入状态 class 并派发 invalid 事件", async () => {
    document.body.innerHTML = `
      <form data-om-component="form-validator" novalidate>
        <input name="name" required>
        <button type="submit">Submit</button>
      </form>
    `;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const component = new FormValidator(form);
    let invalidControls = 0;

    form.addEventListener("om:form-validator:invalid", (event) => {
      invalidControls = (event as CustomEvent).detail.controls.length;
    });
    await component.start();

    const event = new Event("submit", { bubbles: true, cancelable: true });
    const wasNotCanceled = form.dispatchEvent(event);

    expect(wasNotCanceled).toBe(false);
    expect(form.classList.contains("was-validated")).toBe(true);
    expect(invalidControls).toBe(1);

    await component.stop();
    document.body.replaceChildren();
  });

  it("有效提交时不阻止提交并派发 valid 事件", async () => {
    document.body.innerHTML = `
      <form data-om-component="form-validator" novalidate>
        <input name="name" value="Alex" required>
        <button type="submit">Submit</button>
      </form>
    `;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const component = new FormValidator(form);
    let validEvents = 0;

    form.addEventListener("om:form-validator:valid", () => {
      validEvents += 1;
    });
    await component.start();

    const event = new Event("submit", { bubbles: true, cancelable: true });
    const wasNotCanceled = form.dispatchEvent(event);

    expect(wasNotCanceled).toBe(true);
    expect(form.classList.contains("was-validated")).toBe(true);
    expect(validEvents).toBe(1);

    await component.stop();
    document.body.replaceChildren();
  });

  it("reset 时清理可配置的校验状态 class", async () => {
    document.body.innerHTML = `
      <section data-om-form-validation-class="is-validated">
        <form novalidate>
          <input name="name" required>
        </form>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const component = new FormValidator(root);

    await component.start();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(form.classList.contains("is-validated")).toBe(true);

    form.dispatchEvent(new Event("reset", { bubbles: true }));
    expect(form.classList.contains("is-validated")).toBe(false);

    await component.stop();
    document.body.replaceChildren();
  });

  it("支持作为表单内部的轻量子组件校验父表单", async () => {
    document.body.innerHTML = `
      <form novalidate>
        <span data-om-component="form-validator" hidden></span>
        <input name="name" required>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='form-validator']")!;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const component = new FormValidator(root);

    await component.start();
    const wasNotCanceled = form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    expect(wasNotCanceled).toBe(false);
    expect(form.classList.contains("was-validated")).toBe(true);

    await component.stop();
    document.body.replaceChildren();
  });
});
