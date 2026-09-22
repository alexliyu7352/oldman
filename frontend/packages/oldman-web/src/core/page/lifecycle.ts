import { getOldmanContext } from "../runtime/context";
import type { PageConstructor } from "./page";
import type { PageLoader, PageRegistry } from "./registry";
import { ScopedPreloader } from "../services/preloader";
import { querySelfOrDescendant } from "../dom/helpers";

export type StopPageLifecycle = () => Promise<void>;

interface TurboVisitDetail {
  action?: string;
}

interface TurboFrameRenderDetail {
  newFrame: HTMLElement;
  resume: () => void;
}

export interface StartPageLifecycleOptions {
  registry?: PageRegistry;
  document?: Document;
  loadPage?: PageLoader;
  fallbackPage?: PageConstructor;
}

export async function startPageLifecycle(options: StartPageLifecycleOptions = {}): Promise<StopPageLifecycle> {
  const context = getOldmanContext();
  const registry = options.registry ?? context.pageRegistry;
  const ownerDocument = options.document ?? context.document;
  const mountOptions = {
    ...(options.loadPage ? { loadPage: options.loadPage } : {}),
    ...(options.fallbackPage ? { fallbackPage: options.fallbackPage } : {}),
    logger: context.logger
  };
  let stopped = false;
  let skipNextAdvanceBeforeRender = false;
  let frameAdvanceDocumentEventsPending = false;
  let mainFrameSelector: string | null = null;

  const mountPage = async () => {
    const page = await registry.mount(ownerDocument, mountOptions);
    // Keep the last mounted Page's selector while unmount temporarily clears current.
    mainFrameSelector = registry.current?.mainFrameSelector ?? mainFrameSelector;
    return page;
  };

  const isMainFrame = (frame: EventTarget | null): frame is HTMLElement => {
    if (!(frame instanceof HTMLElement)) return false;
    // The Page may still be mounting, or even waiting for its class import.
    const selector = registry.current?.mainFrameSelector ?? mainFrameSelector;
    if (selector) {
      mainFrameSelector = selector;
      return frame.matches(selector);
    }
    return frame.matches("turbo-frame[data-om-page]");
  };

  const beforeFrameRender = (event: Event) => {
    const frame = event.target;
    if (stopped || !isMainFrame(frame)) return;
    const { newFrame, resume } = (event as CustomEvent<TurboFrameRenderDetail>).detail;
    const root = registry.current?.root
      ?? querySelfOrDescendant<HTMLElement>(ownerDocument, "[data-om-page]");

    // Turbo does not await a custom Frame render function. Pause before it mutates
    // the DOM so asynchronous Page cleanup cannot touch the next Page's components.
    event.preventDefault();
    frame.dataset.omFrameState = "rendering";
    void registry.unmount().catch(reportLifecycleError).finally(() => {
      const pageName = newFrame.dataset.omPage ?? root?.dataset.omPage;
      if (pageName && frame.isConnected) {
        frame.dataset.omPage = pageName;
        if (root) root.dataset.omPage = pageName;
      }
      resume();
    });
  };

  const frameRender = (event: Event) => {
    const frame = event.target;
    if (stopped || !isMainFrame(frame)) return;
    if (frame.getAttribute("data-turbo-action") === "advance") {
      skipNextAdvanceBeforeRender = true;
      frameAdvanceDocumentEventsPending = true;
    }
    // This navigation has one Page mount. The promoted document events below
    // must not mount it again or clear its newly created component preloaders.
    ScopedPreloader.clearWithin(frame);
    frame.dataset.omFrameState = "mounting";
    void mountPage().then((page) => {
      if (page && registry.current === page && !page.signal.aborted) {
        frame.dataset.omFrameState = "mounted";
      }
    }).catch((error: unknown) => {
      frame.dataset.omFrameState = "failed";
      ScopedPreloader.clearWithin(frame);
      reportLifecycleError(error);
    });
  };

  const visit = (event: Event) => {
    const action = (event as CustomEvent<TurboVisitDetail>).detail?.action;
    if (action !== "restore") return;

    // History restoration supersedes any promoted frame visit whose document
    // completion events have not arrived yet.
    skipNextAdvanceBeforeRender = false;
    frameAdvanceDocumentEventsPending = false;
  };

  const beforeRender = (event: Event) => {
    if (skipNextAdvanceBeforeRender && event.target === ownerDocument.documentElement) {
      skipNextAdvanceBeforeRender = false;
      return;
    }

    skipNextAdvanceBeforeRender = false;
    frameAdvanceDocumentEventsPending = false;
    // Document/history renders need the same cleanup-before-DOM boundary as Frames.
    const resume = (event as CustomEvent<{ resume?: () => void }>).detail?.resume;
    if (resume) event.preventDefault();
    void registry.unmount().catch(reportLifecycleError).finally(() => resume?.());
  };

  const load = () => {
    if (frameAdvanceDocumentEventsPending) {
      frameAdvanceDocumentEventsPending = false;
      return;
    }
    ScopedPreloader.clearWithin(ownerDocument);
    if (!stopped) void mountPage().catch(reportLifecycleError);
  };

  const beforeCache = () => {
    if (frameAdvanceDocumentEventsPending) return;
    ScopedPreloader.clearWithin(ownerDocument);
    const frame = mainFrameSelector ? ownerDocument.querySelector<HTMLElement>(mainFrameSelector) : null;
    if (frame) frame.dataset.omFrameState = "mounted";
  };

  const render = () => {
    if (frameAdvanceDocumentEventsPending) return;
    ScopedPreloader.clearWithin(ownerDocument);
  };

  ownerDocument.addEventListener("turbo:before-cache", beforeCache);
  ownerDocument.addEventListener("turbo:before-render", beforeRender);
  ownerDocument.addEventListener("turbo:before-frame-render", beforeFrameRender);
  ownerDocument.addEventListener("turbo:frame-render", frameRender);
  ownerDocument.addEventListener("turbo:render", render);
  ownerDocument.addEventListener("turbo:load", load);
  ownerDocument.addEventListener("turbo:visit", visit);

  try {
    await mountPage();
  } catch (error) {
    ownerDocument.removeEventListener("turbo:before-cache", beforeCache);
    ownerDocument.removeEventListener("turbo:before-render", beforeRender);
    ownerDocument.removeEventListener("turbo:before-frame-render", beforeFrameRender);
    ownerDocument.removeEventListener("turbo:frame-render", frameRender);
    ownerDocument.removeEventListener("turbo:render", render);
    ownerDocument.removeEventListener("turbo:load", load);
    ownerDocument.removeEventListener("turbo:visit", visit);
    throw error;
  }

  return async () => {
    stopped = true;
    ownerDocument.removeEventListener("turbo:before-cache", beforeCache);
    ownerDocument.removeEventListener("turbo:before-render", beforeRender);
    ownerDocument.removeEventListener("turbo:before-frame-render", beforeFrameRender);
    ownerDocument.removeEventListener("turbo:frame-render", frameRender);
    ownerDocument.removeEventListener("turbo:render", render);
    ownerDocument.removeEventListener("turbo:load", load);
    ownerDocument.removeEventListener("turbo:visit", visit);
    await registry.unmount();
  };
}

function reportLifecycleError(error: unknown): void {
  console.error("Oldman page lifecycle task failed", error);
}
