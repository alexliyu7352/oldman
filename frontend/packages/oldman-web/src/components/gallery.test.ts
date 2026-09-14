import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentManager } from "../core/component/manager";
import { Gallery } from "./gallery";

describe("Gallery", () => {
  afterEach(() => document.body.replaceChildren());

  it("selects the requested slide when its Modal opens and shows image fallbacks", async () => {
    document.body.innerHTML = `
      <div>
        <button data-om-gallery-item data-om-gallery-index="2"></button>
        <div data-gallery-modal>
          <div data-om-gallery-carousel></div>
        </div>
        <span><img data-om-gallery-image><span data-om-gallery-fallback hidden>Unavailable</span></span>
      </div>
    `;
    const root = document.body.firstElementChild as HTMLElement;
    const carousel = { slideTo: vi.fn() };
    const manager = { get: vi.fn(() => carousel) } as unknown as ComponentManager;
    const component = new Gallery(root, { manager });

    await component.start();
    root.querySelector<HTMLElement>("[data-om-gallery-item]")?.click();
    root.querySelector<HTMLElement>("[data-gallery-modal]")?.dispatchEvent(new CustomEvent("om:modal:open", { bubbles: true }));

    expect(carousel.slideTo).toHaveBeenCalledWith(2);

    const image = root.querySelector<HTMLImageElement>("[data-om-gallery-image]")!;
    image.dispatchEvent(new Event("error"));
    expect(image.hidden).toBe(true);
    expect(root.querySelector<HTMLElement>("[data-om-gallery-fallback]")?.hidden).toBe(false);
  });
});
