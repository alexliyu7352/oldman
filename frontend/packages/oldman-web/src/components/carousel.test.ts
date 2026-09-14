import { afterEach, describe, expect, it, vi } from "vitest";

const swiperRuntime = vi.hoisted(() => ({
  constructor: vi.fn(),
  destroy: vi.fn(),
  slideTo: vi.fn(),
  update: vi.fn()
}));

vi.mock("swiper", () => ({
  default: class {
    constructor(element: HTMLElement, options: object) {
      swiperRuntime.constructor(element, options);
    }

    destroy(...args: unknown[]) {
      swiperRuntime.destroy(...args);
    }

    slideTo(...args: unknown[]) {
      swiperRuntime.slideTo(...args);
    }

    update(...args: unknown[]) {
      swiperRuntime.update(...args);
    }
  }
}));

vi.mock("swiper/modules", () => ({
  A11y: "a11y",
  Keyboard: "keyboard",
  Navigation: "navigation",
  Pagination: "pagination"
}));

import { Carousel } from "./carousel";

describe("Carousel", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.clearAllMocks();
  });

  it("initializes responsive horizontal browsing and destroys Swiper on unmount", async () => {
    document.body.innerHTML = `
      <section
        data-om-component="carousel"
        data-om-carousel-options='{"slidesPerView":1,"breakpoints":{"768":{"slidesPerView":3}}}'
      >
        <div data-om-carousel-viewport></div>
        <button data-om-carousel-prev></button>
        <button data-om-carousel-next></button>
        <div data-om-carousel-pagination></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='carousel']")!;
    const viewport = root.querySelector<HTMLElement>("[data-om-carousel-viewport]")!;
    const previous = root.querySelector<HTMLElement>("[data-om-carousel-prev]")!;
    const next = root.querySelector<HTMLElement>("[data-om-carousel-next]")!;
    const pagination = root.querySelector<HTMLElement>("[data-om-carousel-pagination]")!;
    const component = new Carousel(root);

    await component.start();

    expect(swiperRuntime.constructor).toHaveBeenCalledWith(viewport, expect.objectContaining({
      a11y: { enabled: true },
      breakpoints: { 768: { slidesPerView: 3 } },
      keyboard: { enabled: true, onlyInViewport: true },
      modules: ["a11y", "keyboard", "navigation", "pagination"],
      navigation: { nextEl: next, prevEl: previous },
      pagination: { clickable: true, el: pagination },
      slidesPerView: 1
    }));
    expect(root.dataset.omCarouselState).toBe("ready");

    component.slideTo(2);

    expect(swiperRuntime.update).toHaveBeenCalledOnce();
    expect(swiperRuntime.slideTo).toHaveBeenCalledWith(2, 0);

    await component.stop();

    expect(swiperRuntime.destroy).toHaveBeenCalledWith(true, true);
    expect(root.dataset.omCarouselState).toBeUndefined();
  });
});
