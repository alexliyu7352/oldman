import { describe, expect, it } from "vitest";
import { ComponentManager, ComponentRegistry } from "../core/index";
import { FormValidator } from "./form-validator";
import { MultiStepForm } from "./multi-step-form";

describe("MultiStepForm", () => {
  it("逐步校验、前后切换并把服务器字段错误定位到对应步骤", async () => {
    document.body.innerHTML = `
      <form novalidate>
        <span data-om-component="form-validator" hidden></span>
        <div data-om-component="multi-step-form">
          <ol>
            <li data-om-step-indicator="0"></li>
            <li data-om-step-indicator="1"></li>
          </ol>
          <section data-om-step-panel="0"><input name="name" required></section>
          <section data-om-step-panel="1"><input name="email" type="email" required></section>
          <div data-om-step-navigation hidden>
            <button type="button" data-om-step-previous>Previous</button>
            <button type="button" data-om-step-next>Next</button>
          </div>
        </div>
        <div data-om-form-actions><button type="submit">Finish</button></div>
      </form>
    `;
    const registry = new ComponentRegistry();
    registry.register(FormValidator);
    registry.register(MultiStepForm);
    const manager = new ComponentManager({ registry });
    await manager.mount(document.body);

    const form = document.querySelector("form")!;
    const panels = Array.from(document.querySelectorAll<HTMLElement>("[data-om-step-panel]"));
    const next = document.querySelector<HTMLButtonElement>("[data-om-step-next]")!;
    const previous = document.querySelector<HTMLButtonElement>("[data-om-step-previous]")!;
    const actions = document.querySelector<HTMLElement>("[data-om-form-actions]")!;

    next.click();
    expect(panels[0]?.hidden).toBe(false);
    expect(actions.hidden).toBe(true);

    document.querySelector<HTMLInputElement>("[name='name']")!.value = "Alex";
    next.click();
    expect(panels[0]?.hidden).toBe(true);
    expect(panels[1]?.hidden).toBe(false);
    expect(actions.hidden).toBe(false);

    previous.click();
    expect(panels[0]?.hidden).toBe(false);
    document.querySelector<HTMLInputElement>("[name='email']")!.setAttribute("aria-invalid", "true");
    form.dispatchEvent(new CustomEvent("om:form:error"));
    expect(panels[1]?.hidden).toBe(false);

    await manager.unmount(document.body);
    document.body.replaceChildren();
  });
});
