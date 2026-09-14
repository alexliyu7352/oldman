import { afterEach, describe, expect, it } from "vitest";
import { Slider } from "./slider";

describe("Slider", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("根据 JSON 配置初始化 noUiSlider 并派发更新事件", async () => {
    document.body.innerHTML = `
      <div
        data-om-component="slider"
        data-om-slider-options='{"start":10,"connect":"lower","range":{"min":0,"max":100}}'
      ></div>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='slider']")!;
    const component = new Slider(root);
    let updateCount = 0;

    root.addEventListener("om:slider:update", () => {
      updateCount += 1;
    });
    await component.start();

    expect(root.classList.contains("noUi-target")).toBe(true);
    component.set(30);
    expect(Number(component.get(true))).toBe(30);
    expect(updateCount).toBeGreaterThan(0);

    await component.stop();
    expect(root.classList.contains("noUi-target")).toBe(false);
    expect((root as HTMLElement & { noUiSlider?: unknown }).noUiSlider).toBeUndefined();
  });

  it("支持通过 data 属性配置 wNumb 小数位", async () => {
    document.body.innerHTML = `
      <div
        data-om-component="slider"
        data-om-slider-format-decimals="0"
        data-om-slider-options='{"start":12.6,"range":{"min":0,"max":100}}'
      ></div>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='slider']")!;
    const component = new Slider(root);
    await component.start();

    expect(component.get()).toBe("13");

    await component.stop();
  });

  it("可把范围值写回筛选表单并在 change 时提交", async () => {
    document.body.innerHTML = `
      <form id="filters">
        <input name="confidence_min" value="">
        <input name="confidence_max" value="">
      </form>
      <div
        data-om-component="slider"
        data-om-slider-min-input="confidence_min"
        data-om-slider-max-input="confidence_max"
        data-om-slider-form-selector="#filters"
        data-om-slider-submit-on-change="true"
        data-om-slider-options='{"start":[0,100],"connect":true,"range":{"min":0,"max":100},"step":1}'
      ></div>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='slider']")!;
    const form = document.querySelector<HTMLFormElement>("#filters")!;
    const min = document.querySelector<HTMLInputElement>("[name='confidence_min']")!;
    const max = document.querySelector<HTMLInputElement>("[name='confidence_max']")!;
    let submitCount = 0;
    form.requestSubmit = () => {
      submitCount += 1;
    };
    const component = new Slider(root);

    await component.start();
    component.set([25, 75]);

    expect(min.value).toBe("25");
    expect(max.value).toBe("75");
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(submitCount).toBeGreaterThan(0);

    await component.stop();
  });
});
