import { afterEach, describe, expect, it, vi } from "vitest";
import Cleave from "cleave.js";
import { FormMask } from "./form-mask";

const cleaveMock = vi.mocked(Cleave);
const cleaveState = vi.hoisted(() => ({
  destroyCalls: [] as ReturnType<typeof vi.fn>[],
  getRawValueCalls: [] as ReturnType<typeof vi.fn>[],
  setRawValueCalls: [] as ReturnType<typeof vi.fn>[]
}));

vi.mock("cleave.js", () => ({
  default: vi.fn(() => {
    const destroy = vi.fn();
    const getRawValue = vi.fn(() => "123456");
    const setRawValue = vi.fn();
    cleaveState.destroyCalls.push(destroy);
    cleaveState.getRawValueCalls.push(getRawValue);
    cleaveState.setRawValueCalls.push(setRawValue);
    return { destroy, getRawValue, setRawValue };
  })
}));

describe("FormMask", () => {
  afterEach(() => {
    document.body.replaceChildren();
    cleaveMock.mockClear();
    cleaveState.destroyCalls = [];
    cleaveState.getRawValueCalls = [];
    cleaveState.setRawValueCalls = [];
  });

  it("根据预设类型初始化 Cleave 配置", async () => {
    document.body.innerHTML = `<input data-om-mask-type="date">`;
    const input = document.querySelector<HTMLInputElement>("input")!;
    const component = new FormMask(input);

    await component.start();

    expect(cleaveMock).toHaveBeenCalledWith(
      input,
      expect.objectContaining({
        date: true,
        datePattern: ["d", "m", "Y"],
        delimiter: "-"
      })
    );

    await component.stop();
  });

  it("支持 JSON 配置和 data 属性覆盖预设", async () => {
    document.body.innerHTML = `
      <input
        data-om-mask-type="delimiter"
        data-om-mask-options='{"blocks":[2,2]}'
        data-om-mask-delimiter="/"
      >
    `;
    const input = document.querySelector<HTMLInputElement>("input")!;
    const component = new FormMask(input);

    await component.start();

    expect(cleaveMock).toHaveBeenCalledWith(
      input,
      expect.objectContaining({
        blocks: [2, 2],
        delimiter: "/",
        uppercase: true
      })
    );

    await component.stop();
  });

  it("透出原始值、写入原始值并在销毁时释放 Cleave", async () => {
    document.body.innerHTML = `<input data-om-mask-type="phone">`;
    const input = document.querySelector<HTMLInputElement>("input")!;
    const component = new FormMask(input);

    await component.start();
    expect(component.rawValue()).toBe("123456");

    component.setRawValue("987654");
    expect(cleaveState.setRawValueCalls[0]).toHaveBeenCalledWith("987654");

    await component.stop();
    expect(cleaveState.destroyCalls[0]).toHaveBeenCalledTimes(1);
  });
});
