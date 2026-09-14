import { afterEach, describe, expect, it } from "vitest";
import { SlugInput } from "./slug-input";

describe("SlugInput", () => {
  afterEach(() => document.body.replaceChildren());

  it("tracks its source until the user supplies a custom slug", async () => {
    document.body.innerHTML = `
      <form>
        <input id="id_title" name="title">
        <input name="slug" data-om-slug-source="#id_title">
      </form>
    `;
    const source = document.querySelector<HTMLInputElement>("#id_title")!;
    const target = document.querySelector<HTMLInputElement>("[name='slug']")!;
    await new SlugInput(target).start();

    input(source, "Café Release Notes");
    expect(target.value).toBe("cafe-release-notes");

    input(target, "My Custom Path!");
    expect(target.value).toBe("my-custom-path");
    input(source, "A Later Title");
    expect(target.value).toBe("my-custom-path");

    input(target, "");
    expect(target.value).toBe("a-later-title");
    input(source, "Final Title");
    expect(target.value).toBe("final-title");
  });

  it("keeps Unicode letters when the field requests them", async () => {
    document.body.innerHTML = `
      <form>
        <input id="id_title" name="title">
        <input name="slug" data-om-slug-source="#id_title" data-om-slug-allow-unicode="true">
      </form>
    `;
    const source = document.querySelector<HTMLInputElement>("#id_title")!;
    const target = document.querySelector<HTMLInputElement>("[name='slug']")!;
    await new SlugInput(target).start();

    input(source, "中文 发布页面");

    expect(target.value).toBe("中文-发布页面");
  });
});

function input(element: HTMLInputElement, value: string): void {
  element.value = value;
  element.dispatchEvent(new Event("input", { bubbles: true }));
}
