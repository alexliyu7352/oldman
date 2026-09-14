import { describe, expect, it } from "vitest";
import { Popover } from "./popover";

describe("Popover", () => {
  it("toggles from its trigger and closes from an outside click", async () => {
    document.body.innerHTML = `
      <div data-om-component="popover">
        <button data-om-popover-trigger aria-controls="account-popover">Account</button>
        <div id="account-popover" data-om-popover-content><a href="/profile">Profile</a></div>
      </div>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='popover']")!;
    const trigger = root.querySelector<HTMLButtonElement>("button")!;
    const content = root.querySelector<HTMLElement>("[data-om-popover-content]")!;
    const popover = new Popover(root);

    await popover.start();
    trigger.click();
    expect(content.hidden).toBe(false);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    document.body.click();
    expect(content.hidden).toBe(true);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await popover.stop();
  });
});
