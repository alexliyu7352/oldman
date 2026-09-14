import { afterEach, describe, expect, it, vi } from "vitest";

const pickr = vi.hoisted(() => {
  const handlers = new Map<string, (...args: unknown[]) => void>();
  const instance = {
    destroyAndRemove: vi.fn(),
    getColor: vi.fn(),
    hide: vi.fn(),
    on: vi.fn((name: string, callback: (...args: unknown[]) => void) => {
      handlers.set(name, callback);
      return instance;
    }),
    setColor: vi.fn()
  };
  return { create: vi.fn(() => instance), handlers, instance };
});

vi.mock("@simonwep/pickr", () => ({ default: { create: pickr.create } }));

import { ColorPicker } from "./color-picker";

describe("ColorPicker", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.clearAllMocks();
    pickr.handlers.clear();
  });

  it("progressively enhances the native input and submits an alpha HEX value", async () => {
    document.body.innerHTML = `
      <form>
        <div data-om-color-picker-alpha="true">
          <input type="color" name="accent" value="#0ea5e9" data-om-color-picker-native>
          <input type="hidden" value="#0ea5e9cc" data-om-color-picker-value disabled>
          <button type="button" data-om-color-picker-trigger hidden></button>
        </div>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-color-picker-alpha]")!;
    const native = root.querySelector<HTMLInputElement>("[data-om-color-picker-native]")!;
    const value = root.querySelector<HTMLInputElement>("[data-om-color-picker-value]")!;
    const trigger = root.querySelector<HTMLButtonElement>("[data-om-color-picker-trigger]")!;
    const component = new ColorPicker(root);

    await component.start();
    expect(native.hidden).toBe(true);
    expect(native.name).toBe("");
    expect(value.name).toBe("accent");
    expect(value.disabled).toBe(false);
    expect(trigger.hidden).toBe(false);

    pickr.handlers.get("change")?.({ toHEXA: () => ({ toString: () => "#22C55E80" }) });
    expect(value.value).toBe("#22c55e80");
    expect(native.value).toBe("#22c55e");

    pickr.instance.getColor.mockReturnValue({ toHEXA: () => ({ toString: () => "#0EA5E9CC" }) });
    pickr.handlers.get("cancel")?.();
    expect(value.value).toBe("#0ea5e9cc");
    expect(native.value).toBe("#0ea5e9");

    root.closest("form")?.reset();
    await Promise.resolve();
    expect(pickr.instance.setColor).toHaveBeenCalledWith("#0ea5e9cc", true);

    await component.stop();
    expect(pickr.instance.destroyAndRemove).toHaveBeenCalledOnce();
    expect(native.hidden).toBe(false);
    expect(native.name).toBe("accent");
    expect(value.name).toBe("");
    expect(value.disabled).toBe(true);
    expect(trigger.hidden).toBe(true);
  });
});
