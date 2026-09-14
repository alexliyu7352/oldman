import { Modal, type ModalOptions } from "../components/modal";

export interface DashboardModalOptions extends ModalOptions {}

export const DASHBOARD_MODAL_SURFACE_SELECTOR = "[data-om-modal-surface], .om-modal-surface";
export const DASHBOARD_MODAL_CONTENT_SELECTOR = "[data-om-modal-content], .om-modal-body";
export const DASHBOARD_MODAL_FOOTER_SELECTOR = "[data-om-modal-footer], .om-modal-footer";
export const DASHBOARD_MODAL_TITLE_SELECTOR = "[data-om-modal-title], .om-modal-title";
export const DASHBOARD_MODAL_BACKDROP_CLASS = "om-modal-backdrop";
export const DASHBOARD_MODAL_BODY_OPEN_CLASS = "om-modal-open";
export const DASHBOARD_MODAL_DIALOG_SELECTOR = "[data-om-modal-dialog], .om-modal-dialog";
export const DASHBOARD_MODAL_OPEN_CLASS = "is-open";
export const DASHBOARD_MODAL_TRANSITION_FALLBACK_MS = 160;

/** Shared Dashboard/Admin theme adapter for the headless Modal component. */
export class DashboardModal extends Modal {
  constructor(root: HTMLElement, options: DashboardModalOptions = {}) {
    super(root, {
      ...options,
      backdropClass: options.backdropClass ?? DASHBOARD_MODAL_BACKDROP_CLASS,
      backdropOpenClass: options.backdropOpenClass ?? DASHBOARD_MODAL_OPEN_CLASS,
      bodyOpenClass: options.bodyOpenClass ?? DASHBOARD_MODAL_BODY_OPEN_CLASS,
      closeOnEscape: options.closeOnEscape ?? root.dataset.omKeyboard !== "false",
      closeOnOutside: options.closeOnOutside ?? root.dataset.omBackdrop !== "static",
      contentSelector: options.contentSelector ?? DASHBOARD_MODAL_CONTENT_SELECTOR,
      footerSelector: options.footerSelector ?? DASHBOARD_MODAL_FOOTER_SELECTOR,
      forceReflowOnOpen: options.forceReflowOnOpen ?? true,
      hiddenDisplay: options.hiddenDisplay ?? "none",
      openClass: options.openClass ?? DASHBOARD_MODAL_OPEN_CLASS,
      surfaceSelector: options.surfaceSelector ?? DASHBOARD_MODAL_SURFACE_SELECTOR,
      titleSelector: options.titleSelector ?? DASHBOARD_MODAL_TITLE_SELECTOR,
      transitionElementSelector: options.transitionElementSelector ?? DASHBOARD_MODAL_DIALOG_SELECTOR,
      transitionFallbackMs: options.transitionFallbackMs ?? DASHBOARD_MODAL_TRANSITION_FALLBACK_MS,
      visibleDisplay: options.visibleDisplay ?? "block"
    });
  }

  override async mount(): Promise<void> {
    this.normalizeInitialState();
    await super.mount();
    this.root.dataset.omModalManaged = "true";

    const surface = this.root.querySelector<HTMLElement>(DASHBOARD_MODAL_SURFACE_SELECTOR);
    if (surface && !surface.hasAttribute("tabindex")) {
      surface.setAttribute("tabindex", "-1");
    }
  }

  private normalizeInitialState(): void {
    if (this.root.hidden || this.root.classList.contains(DASHBOARD_MODAL_OPEN_CLASS)) return;
    if (this.root.style.display === "block") return;

    this.root.hidden = true;
    this.root.setAttribute("aria-hidden", "true");
    this.root.style.display = "none";
  }
}
