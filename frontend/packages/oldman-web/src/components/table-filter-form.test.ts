import { describe, expect, it } from "vitest";
import { TableFilterForm } from "./table-filter-form";

class RecordingFilterForm extends TableFilterForm {
  submitted: HTMLFormElement[] = [];

  override async submitFilterForm(form = this.root as HTMLFormElement): Promise<void> {
    this.submitted.push(form);
  }
}

describe("TableFilterForm", () => {
  it("clears every filter value on reset and resubmits", async () => {
    document.body.innerHTML = `
      <form data-om-component="table-filter-form" data-om-table-target="#records" data-om-layout="inline">
        <input type="hidden" name="page" value="3">
        <input type="search" name="q" value="alice">
        <select name="is_active"><option value="">All</option><option value="true" selected>Yes</option></select>
        <input type="text" name="from" value="2026-09-01">
        <input type="checkbox" name="flag" checked>
        <button type="button" data-om-filter-reset>Reset</button>
      </form>
    `;
    const root = document.querySelector<HTMLFormElement>("form")!;
    const component = new RecordingFilterForm(root);
    await component.start();

    try {
      root.querySelector<HTMLButtonElement>("[data-om-filter-reset]")!.click();
      await Promise.resolve();

      expect(root.querySelector<HTMLInputElement>('[name="q"]')!.value).toBe("");
      expect(root.querySelector<HTMLSelectElement>('[name="is_active"]')!.value).toBe("");
      expect(root.querySelector<HTMLInputElement>('[name="from"]')!.value).toBe("");
      expect(root.querySelector<HTMLInputElement>('[name="flag"]')!.checked).toBe(false);
      expect(root.querySelector<HTMLInputElement>('[name="page"]')!.value).toBe("3");
      expect(component.submitted).toEqual([root]);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });
});
