import { afterEach, describe, expect, it } from "vitest";
import { TagsInput } from "./tags-input";

describe("TagsInput", () => {
  afterEach(() => document.body.replaceChildren());

  it("normalizes text and commits keyboard and pasted tags to the native input", async () => {
    document.body.innerHTML = '<input name="tags" value=" Python, sanic,,Python ">';
    const input = document.querySelector<HTMLInputElement>("input")!;
    const component = new TagsInput(input);

    await component.start();

    expect(input.value).toBe("Python,sanic");
    const editor = visibleEditor();
    enter(editor, "Redis", "Enter");
    enter(editor, "python", ",");
    paste(editor, "API, worker,API");

    expect(input.value).toBe("Python,sanic,Redis,python,API,worker");

    editor.value = "";
    editor.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Backspace" }));
    expect(input.value).toBe("Python,sanic,Redis,python,API");

    await component.stop();
    expect(document.querySelector(".choices")).toBeNull();
  });

  it("uses the configured delimiter and commits pending text before blur or submit", async () => {
    document.body.innerHTML = `
      <form>
        <input name="tags" value="api|web" data-om-tags-delimiter="|">
      </form>
    `;
    const form = document.querySelector<HTMLFormElement>("form")!;
    const input = document.querySelector<HTMLInputElement>("input")!;
    const component = new TagsInput(input);
    await component.start();

    const editor = visibleEditor();
    editor.value = "worker";
    editor.dispatchEvent(new FocusEvent("blur"));
    expect(input.value).toBe("api|web|worker");

    editor.value = "dashboard";
    form.addEventListener("submit", () => expect(input.value).toBe("api|web|worker|dashboard"));
    form.dispatchEvent(new SubmitEvent("submit", { bubbles: true, cancelable: true }));

    await component.stop();
  });

  it("restores the normalized initial value when the form resets", async () => {
    document.body.innerHTML = '<form><input name="tags" value=" Python, Sanic "></form>';
    const form = document.querySelector<HTMLFormElement>("form")!;
    const input = document.querySelector<HTMLInputElement>("input")!;
    const component = new TagsInput(input);
    await component.start();

    enter(visibleEditor(), "Redis", "Enter");
    expect(input.value).toBe("Python,Sanic,Redis");

    form.reset();
    await Promise.resolve();
    expect(input.value).toBe("Python,Sanic");

    await component.stop();
  });

  it("does not commit Enter while an IME composition is active", async () => {
    document.body.innerHTML = '<input name="tags">';
    const input = document.querySelector<HTMLInputElement>("input")!;
    const component = new TagsInput(input);
    await component.start();

    const editor = visibleEditor();
    editor.value = "中文";
    editor.dispatchEvent(new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      isComposing: true,
      key: "Enter"
    }));

    expect(input.value).toBe("");
    expect(editor.value).toBe("中文");
    await component.stop();
  });

  it("moves validation focus from the hidden control to the visible editor", async () => {
    document.body.innerHTML = '<input name="tags">';
    const input = document.querySelector<HTMLInputElement>("input")!;
    const component = new TagsInput(input);
    await component.start();

    input.dispatchEvent(new Event("invalid"));

    expect(document.activeElement).toBe(visibleEditor());
    await component.stop();
  });
});

function visibleEditor(): HTMLInputElement {
  return document.querySelector<HTMLInputElement>(".choices__input--cloned")!;
}

function enter(editor: HTMLInputElement, value: string, key: string): void {
  editor.value = value;
  editor.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key }));
}

function paste(editor: HTMLInputElement, value: string): void {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", { value: { getData: () => value } });
  editor.dispatchEvent(event);
}
