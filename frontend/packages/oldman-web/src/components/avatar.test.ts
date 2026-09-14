import { describe, expect, it } from "vitest";
import { Avatar } from "./avatar";

describe("Avatar", () => {
  it("shows fallback content after the image fails", async () => {
    document.body.innerHTML = `
      <span>
        <img data-om-avatar-image src="/missing.png" alt="Alex">
        <span data-om-avatar-fallback hidden>AL</span>
      </span>
    `;
    const root = document.querySelector<HTMLElement>("span")!;
    const image = root.querySelector<HTMLImageElement>("img")!;
    const fallback = root.querySelector<HTMLElement>("[data-om-avatar-fallback]")!;
    const avatar = new Avatar(root);

    await avatar.start();
    image.dispatchEvent(new Event("error"));

    expect(image.hidden).toBe(true);
    expect(fallback.hidden).toBe(false);
    expect(root.dataset.omAvatarState).toBe("fallback");
    await avatar.stop();
  });
});
