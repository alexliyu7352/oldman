import { afterEach, describe, expect, it, vi } from "vitest";
import flatpickr from "flatpickr";
import { DateTimePicker } from "./date-time-picker";

const flatpickrMock = vi.mocked(flatpickr);
const flatpickrState = vi.hoisted(() => ({
  destroyCalls: [] as ReturnType<typeof vi.fn>[]
}));

vi.mock("flatpickr", () => ({
  default: vi.fn(() => {
    const destroy = vi.fn();
    flatpickrState.destroyCalls.push(destroy);
    return { destroy };
  })
}));

describe("DateTimePicker", () => {
  afterEach(() => {
    document.body.replaceChildren();
    flatpickrMock.mockClear();
    flatpickrState.destroyCalls = [];
  });

  it("根据 data-provider 初始化日期选择器配置", async () => {
    document.body.innerHTML = `
      <input
        data-provider="flatpickr"
        data-date-format="d M, Y"
        data-enable-time
        data-altFormat="F j, Y"
        data-minDate="01 Jan, 2026"
        data-maxDate="31 Dec, 2026"
        data-deafult-date="today"
        data-range-date="true"
        data-week-number
      >
    `;
    const input = document.querySelector<HTMLInputElement>("[data-provider]")!;
    const component = new DateTimePicker(input);

    await component.start();

    expect(flatpickrMock).toHaveBeenCalledWith(
      input,
      expect.objectContaining({
        altFormat: "F j, Y",
        altInput: true,
        dateFormat: "d M, Y",
        defaultDate: "today",
        disableMobile: true,
        enableTime: true,
        maxDate: "31 Dec, 2026",
        minDate: "01 Jan, 2026",
        mode: "range",
        weekNumbers: true
      })
    );
  });

  it("uses an explicit datetime dateFormat unchanged when time is enabled", async () => {
    document.body.innerHTML = `
      <input
        data-provider="flatpickr"
        data-date-format="Y-m-d\\TH:i"
        data-enable-time
      >
    `;
    const input = document.querySelector<HTMLInputElement>("[data-provider]")!;
    const component = new DateTimePicker(input);

    await component.start();

    expect(flatpickrMock).toHaveBeenCalledWith(
      input,
      expect.objectContaining({
        dateFormat: "Y-m-d\\TH:i",
        disableMobile: true,
        enableTime: true
      })
    );
  });

  it("根据 data-provider 初始化时间选择器配置", async () => {
    document.body.innerHTML = `
      <input
        data-provider="timepickr"
        data-time-hrs="true"
        data-min-time="09:00"
        data-max-time="18:00"
        data-default-time="10:30"
      >
    `;
    const input = document.querySelector<HTMLInputElement>("[data-provider]")!;
    const component = new DateTimePicker(input);

    await component.start();

    expect(flatpickrMock).toHaveBeenCalledWith(
      input,
      expect.objectContaining({
        dateFormat: "H:i",
        defaultDate: "10:30",
        enableTime: true,
        maxTime: "18:00",
        minTime: "09:00",
        noCalendar: true,
        time_24hr: true
      })
    );
  });

  it("销毁 flatpickr 实例并释放页面切换前的事件绑定", async () => {
    document.body.innerHTML = `<input data-provider="flatpickr">`;
    const input = document.querySelector<HTMLInputElement>("[data-provider]")!;
    const component = new DateTimePicker(input);

    await component.start();
    await component.stop();

    expect(flatpickrState.destroyCalls).toHaveLength(1);
    expect(flatpickrState.destroyCalls[0]).toHaveBeenCalledTimes(1);
  });

  it("认得拼写正确的 data-default-date（旧的拼错写法也继续认）", async () => {
    // 实现里写的是 data-deafult-date（deafult），两处;而**仓库里没有任何地方用过正确拼写**。
    // 更要紧的是这个文件原有的用例用的也是错拼写,所以它一直是绿的,等于把这个拼写变成了契约。
    document.body.innerHTML = `
      <div data-om-component="date-time-picker">
        <input data-provider="flatpickr" data-date-format="Y-m-d" data-default-date="2026-09-21">
      </div>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component]")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new DateTimePicker(root);
    await component.start();

    expect(flatpickrMock).toHaveBeenCalledWith(input, expect.objectContaining({ defaultDate: "2026-09-21" }));

    await component.stop();
  });

  it("旧的拼错写法 data-deafult-date 继续有效", async () => {
    document.body.innerHTML = `
      <div data-om-component="date-time-picker">
        <input data-provider="flatpickr" data-date-format="Y-m-d" data-deafult-date="2026-01-02">
      </div>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component]")!;
    const input = root.querySelector<HTMLInputElement>("input")!;
    const component = new DateTimePicker(root);
    await component.start();

    expect(flatpickrMock).toHaveBeenCalledWith(input, expect.objectContaining({ defaultDate: "2026-01-02" }));

    await component.stop();
  });
});
