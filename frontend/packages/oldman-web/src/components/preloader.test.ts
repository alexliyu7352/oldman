import { describe, expect, it } from "vitest";
import { Preloader } from "./preloader";

describe("Preloader", () => {
  it("uses the standard component name and hides after mount", async () => {
    document.documentElement.setAttribute("data-preloader", "disable");
    document.body.innerHTML = preloaderMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='preloader']")!;
    const component = new Preloader(root);

    await component.start();

    try {
      expect(Preloader.componentName).toBe("preloader");
      expect(document.documentElement.getAttribute("data-preloader")).toBe("enable");
      expect(root.hidden).toBe(true);
      expect(root.getAttribute("aria-hidden")).toBe("true");
      expect(root.dataset.omStatus).toBe("idle");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("shows and hides around Turbo navigation and submit events", async () => {
    document.body.innerHTML = preloaderMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='preloader']")!;
    const component = new Preloader(root);

    await component.start();

    try {
      document.dispatchEvent(new Event("turbo:before-visit"));
      expect(document.documentElement.getAttribute("data-preloader")).toBe("enable");
      expect(root.hidden).toBe(false);
      expect(root.getAttribute("aria-hidden")).toBe("false");
      expect(root.dataset.omStatus).toBe("loading");

      document.dispatchEvent(new Event("turbo:load"));
      expect(root.hidden).toBe(true);
      expect(root.dataset.omStatus).toBe("idle");

      document.dispatchEvent(new Event("turbo:submit-start"));
      expect(root.hidden).toBe(false);

      document.dispatchEvent(new Event("turbo:submit-end"));
      expect(root.hidden).toBe(true);

      document.dispatchEvent(new Event("turbo:before-fetch-request"));
      expect(root.hidden).toBe(false);

      document.dispatchEvent(new Event("turbo:fetch-request-error"));
      expect(root.hidden).toBe(true);
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("hides after Turbo frame rendering completes", async () => {
    document.body.innerHTML = preloaderMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='preloader']")!;
    const component = new Preloader(root);

    await component.start();

    try {
      document.dispatchEvent(new Event("turbo:before-fetch-request"));
      expect(root.hidden).toBe(false);
      expect(root.dataset.omStatus).toBe("loading");

      document.dispatchEvent(new Event("turbo:frame-render"));
      expect(root.hidden).toBe(true);
      expect(root.getAttribute("aria-hidden")).toBe("true");
      expect(root.dataset.omStatus).toBe("idle");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("does not show fullscreen preloader for oldman-main frame requests", async () => {
    document.body.innerHTML = `
      ${preloaderMarkup()}
      <turbo-frame id="oldman-main">
        <form id="frame-form"></form>
      </turbo-frame>
    `;
    const root = document.querySelector<HTMLElement>("[data-om-component='preloader']")!;
    const frame = document.querySelector<HTMLElement>("#oldman-main")!;
    const form = document.querySelector<HTMLFormElement>("#frame-form")!;
    const component = new Preloader(root);

    await component.start();

    try {
      frame.dispatchEvent(new Event("turbo:before-fetch-request", { bubbles: true }));
      expect(root.hidden).toBe(true);
      expect(root.dataset.omStatus).toBe("idle");

      form.dispatchEvent(new Event("turbo:submit-start", { bubbles: true }));
      expect(root.hidden).toBe(true);
      expect(root.dataset.omStatus).toBe("idle");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });
});

function preloaderMarkup(): string {
  return `
    <div id="preloader" data-om-component="preloader" role="status" aria-live="polite">
      <div data-om-preloader-status></div>
    </div>
  `;
}
