import { describe, expect, it, vi } from "vitest";
import { Alert } from "./alert";

describe("Alert", () => {
  it("dismisses itself and emits one lifecycle event", async () => {
    document.body.innerHTML = `
      <aside><button type="button" data-om-alert-dismiss>Close</button></aside>
    `;
    const root = document.querySelector<HTMLElement>("aside")!;
    const dismissed = vi.fn();
    root.addEventListener("om:alert:dismiss", dismissed);
    const alert = new Alert(root);

    await alert.start();
    root.querySelector<HTMLButtonElement>("button")!.click();

    expect(root.hidden).toBe(true);
    expect(dismissed).toHaveBeenCalledOnce();
    await alert.stop();
  });
});
