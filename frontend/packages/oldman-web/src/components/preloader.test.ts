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
      expect(progressBar().dataset.omStatus).toBe("idle");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("runs the page progress bar around Turbo navigation and submit events", async () => {
    document.body.innerHTML = preloaderMarkup();
    const root = document.querySelector<HTMLElement>("[data-om-component='preloader']")!;
    const component = new Preloader(root);

    await component.start();

    try {
      document.dispatchEvent(new Event("turbo:before-visit"));
      expect(root.hidden).toBe(true);
      expect(progressBar().dataset.omStatus).toBe("loading");

      document.dispatchEvent(new Event("turbo:load"));
      expect(progressBar().dataset.omStatus).toBe("done");

      document.dispatchEvent(new Event("turbo:submit-start"));
      expect(progressBar().dataset.omStatus).toBe("loading");

      document.dispatchEvent(new Event("turbo:submit-end"));
      expect(progressBar().dataset.omStatus).toBe("done");

      document.dispatchEvent(new Event("turbo:before-fetch-request"));
      expect(progressBar().dataset.omStatus).toBe("loading");

      document.dispatchEvent(new Event("turbo:fetch-request-error"));
      expect(progressBar().dataset.omStatus).toBe("done");
    } finally {
      await component.stop();
      document.body.replaceChildren();
    }
  });

  it("completes the bar after Turbo frame rendering and never re-shows the fullscreen overlay", async () => {
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
      expect(progressBar().dataset.omStatus).toBe("loading");

      frame.dispatchEvent(new Event("turbo:frame-render", { bubbles: true }));
      expect(progressBar().dataset.omStatus).toBe("done");

      frame.dispatchEvent(new Event("turbo:frame-load", { bubbles: true }));
      expect(progressBar().dataset.omStatus).toBe("done");

      form.dispatchEvent(new Event("turbo:submit-start", { bubbles: true }));
      expect(root.hidden).toBe(true);
      expect(progressBar().dataset.omStatus).toBe("loading");
    } finally {
      await component.stop();
      expect(progressBar().dataset.omStatus).toBe("idle");
      document.body.replaceChildren();
    }
  });

  it("stays functional without a progress bar element", async () => {
    document.body.innerHTML = `<div id="preloader" data-om-component="preloader"><div data-om-preloader-status></div></div>`;
    const root = document.querySelector<HTMLElement>("[data-om-component='preloader']")!;
    const component = new Preloader(root);

    await component.start();

    try {
      document.dispatchEvent(new Event("turbo:before-visit"));
      document.dispatchEvent(new Event("turbo:load"));
      expect(root.hidden).toBe(true);
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
    <div class="om-page-progress" data-om-page-progress aria-hidden="true"></div>
  `;
}

function progressBar(): HTMLElement {
  return document.querySelector<HTMLElement>("[data-om-page-progress]")!;
}
