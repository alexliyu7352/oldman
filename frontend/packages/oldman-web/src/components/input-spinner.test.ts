import { afterEach, describe, expect, it, vi } from "vitest";
import { InputSpinner } from "./input-spinner";

const INPUT_SELECTOR = "[data-om-input-spinner-input]";

describe("InputSpinner", () => {
  afterEach(() => document.body.replaceChildren());

  it("steps within native limits and emits normal input events", async () => {
    document.body.innerHTML = `
      <div>
        <button type="button" data-om-input-spinner-decrease>−</button>
        <input type="number" value="2" min="1" max="3" step="0.5" data-om-input-spinner-input>
        <button type="button" data-om-input-spinner-increase>+</button>
      </div>
    `;
    const root = document.body.firstElementChild as HTMLElement;
    const input = root.querySelector<HTMLInputElement>(INPUT_SELECTOR)!;
    const changed = vi.fn();
    input.addEventListener("change", changed);
    const component = new InputSpinner(root);

    await component.start();
    root.querySelector<HTMLButtonElement>("[data-om-input-spinner-increase]")!.click();
    expect(input.value).toBe("2.5");
    expect(changed).toHaveBeenCalledOnce();

    root.querySelector<HTMLButtonElement>("[data-om-input-spinner-increase]")!.click();
    expect(input.value).toBe("3");
    expect(root.querySelector<HTMLButtonElement>("[data-om-input-spinner-increase]")!.disabled).toBe(true);

    input.value = "1";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    expect(root.querySelector<HTMLButtonElement>("[data-om-input-spinner-decrease]")!.disabled).toBe(true);
  });
});
