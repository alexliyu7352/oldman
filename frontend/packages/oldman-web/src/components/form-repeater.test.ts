import { afterEach, describe, expect, it } from "vitest";
import { Component } from "../core/component/component";
import { ComponentManager } from "../core/component/manager";
import { ComponentRegistry } from "../core/component/registry";
import { FormRepeater } from "./form-repeater";

class Probe extends Component {
  static readonly componentName = "probe";
  static mounted = 0;
  static unmounted = 0;

  override async mount(): Promise<void> {
    Probe.mounted += 1;
  }

  override async unmount(): Promise<void> {
    Probe.unmounted += 1;
  }
}

function repeaterHtml(): string {
  return `
    <div
      data-om-component="form-repeater"
      data-om-repeater-name="profile-sources"
      data-om-repeater-id="id_profile-sources"
      data-om-repeater-min="1"
      data-om-repeater-max="3"
    >
      <div data-om-repeater-rows>
        <div data-om-repeater-row>
          <label for="id_profile-sources-0">Source</label>
          <input name="profile-sources-0" id="id_profile-sources-0" aria-describedby="id_profile-sources-0-error">
          <span id="id_profile-sources-0-error" data-om-error-for="profile-sources-0"></span>
          <button type="button" data-om-repeater-up aria-controls="id_profile-sources-0">Up</button>
          <button type="button" data-om-repeater-down aria-controls="id_profile-sources-0">Down</button>
          <button type="button" data-om-repeater-remove aria-controls="id_profile-sources-0">Remove</button>
        </div>
      </div>
      <button type="button" data-om-repeater-add>Add</button>
      <template data-om-repeater-template>
        <div data-om-repeater-row>
          <label for="id_profile-sources-__index__">Source</label>
          <input data-om-component="probe" name="profile-sources-__index__" id="id_profile-sources-__index__" aria-describedby="id_profile-sources-__index__-error">
          <span id="id_profile-sources-__index__-error" data-om-error-for="profile-sources-__index__"></span>
          <button type="button" data-om-repeater-up aria-controls="id_profile-sources-__index__">Up</button>
          <button type="button" data-om-repeater-down aria-controls="id_profile-sources-__index__">Down</button>
          <button type="button" data-om-repeater-remove aria-controls="id_profile-sources-__index__">Remove</button>
        </div>
      </template>
    </div>
  `;
}

function click(selector: string): void {
  document.querySelector<HTMLButtonElement>(selector)!.click();
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("FormRepeater", () => {
  afterEach(() => {
    document.body.replaceChildren();
    Probe.mounted = 0;
    Probe.unmounted = 0;
  });

  it("增删行并完整重排字段属性和动态组件生命周期", async () => {
    document.body.innerHTML = repeaterHtml();
    const registry = new ComponentRegistry();
    registry.register(FormRepeater);
    registry.register(Probe);
    const manager = new ComponentManager({ registry });
    await manager.mount(document);

    click("[data-om-repeater-add]");
    await settle();

    const rows = document.querySelectorAll<HTMLElement>("[data-om-repeater-row]");
    expect(rows).toHaveLength(2);
    const addedRow = rows.item(1);
    expect(addedRow.querySelector("input")?.name).toBe("profile-sources-1");
    expect(addedRow.querySelector("input")?.id).toBe("id_profile-sources-1");
    expect(addedRow.querySelector("label")?.htmlFor).toBe("id_profile-sources-1");
    expect(addedRow.querySelector("input")?.getAttribute("aria-describedby")).toBe("id_profile-sources-1-error");
    expect(addedRow.querySelector("[data-om-error-for]")?.getAttribute("data-om-error-for")).toBe("profile-sources-1");
    expect(addedRow.querySelector("[data-om-repeater-remove]")?.getAttribute("aria-controls")).toBe("id_profile-sources-1");
    expect(Probe.mounted).toBe(1);

    addedRow.querySelector<HTMLButtonElement>("[data-om-repeater-remove]")!.click();
    await settle();
    expect(document.querySelectorAll("[data-om-repeater-row]")).toHaveLength(1);
    expect(Probe.unmounted).toBe(1);

    await manager.unmount(document);
  });

  it("上下移动后连续编号，并遵守 min/max", async () => {
    document.body.innerHTML = repeaterHtml();
    const component = new FormRepeater(document.querySelector<HTMLElement>("[data-om-component='form-repeater']")!);
    await component.start();

    click("[data-om-repeater-add]");
    click("[data-om-repeater-add]");
    await settle();
    expect(document.querySelector<HTMLButtonElement>("[data-om-repeater-add]")!.disabled).toBe(true);

    const inputs = Array.from(document.querySelectorAll<HTMLInputElement>("[data-om-repeater-row] input"));
    inputs.forEach((input, index) => {
      input.value = `source-${index}`;
    });
    document.querySelectorAll<HTMLElement>("[data-om-repeater-row]").item(2)
      .querySelector<HTMLButtonElement>("[data-om-repeater-up]")!
      .click();
    await settle();

    expect(Array.from(document.querySelectorAll<HTMLInputElement>("[data-om-repeater-row] input")).map((input) => input.value)).toEqual([
      "source-0",
      "source-2",
      "source-1"
    ]);
    expect(Array.from(document.querySelectorAll<HTMLInputElement>("[data-om-repeater-row] input")).map((input) => input.name)).toEqual([
      "profile-sources-0",
      "profile-sources-1",
      "profile-sources-2"
    ]);

    document.querySelectorAll<HTMLElement>("[data-om-repeater-row]").item(2)
      .querySelector<HTMLButtonElement>("[data-om-repeater-down]")!
      .click();
    document.querySelectorAll<HTMLElement>("[data-om-repeater-row]").item(1)
      .querySelector<HTMLButtonElement>("[data-om-repeater-remove]")!
      .click();
    document.querySelector<HTMLElement>("[data-om-repeater-row]")!
      .querySelector<HTMLButtonElement>("[data-om-repeater-remove]")!
      .click();
    await settle();

    expect(document.querySelectorAll("[data-om-repeater-row]")).toHaveLength(1);
    expect(document.querySelector<HTMLButtonElement>("[data-om-repeater-remove]")!.disabled).toBe(true);
    await component.stop();
  });
});
