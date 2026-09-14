import { Component } from "../core/component/component";
import { floatingPlacement, positionFloatingElement, resetFloatingPosition } from "../core/dom/floating";
import { querySelfOrDescendant, setHidden } from "../core/dom/helpers";

const POPOVER_TRIGGER_SELECTOR = "[data-om-popover-trigger]";
const POPOVER_CONTENT_SELECTOR = "[data-om-popover-content]";
let popoverId = 0;

/** Toggle an interactive non-modal surface and keep it inside the viewport. */
export class Popover extends Component {
  static readonly componentName = "popover";

  async mount(): Promise<void> {
    const trigger = this.trigger();
    const content = this.content();
    if (!trigger || !content) return;

    if (!content.id) content.id = `om-popover-${++popoverId}`;
    trigger.setAttribute("aria-controls", content.id);
    setHidden(content, true);
    trigger.setAttribute("aria-expanded", "false");
    this.listen<MouseEvent>(trigger, "click", (event) => {
      event.preventDefault();
      this.toggleOpen();
    });
    this.listen<MouseEvent>(document, "click", (event) => {
      const target = event.target;
      if (!content.hidden && target instanceof Node && !this.root.contains(target)) this.close();
    });
    // Tab may leave the surface without closing it; only own Escape in the same Modal.
    this.listen<KeyboardEvent>(document, "keydown", (event) => {
      if (event.key !== "Escape" || content.hidden) return;
      const target = event.target;
      if (!(target instanceof Element)
        || target.closest('[aria-modal="true"]') !== this.root.closest('[aria-modal="true"]')) return;
      event.stopImmediatePropagation();
      this.close();
      trigger.focus();
    }, { capture: true });
    this.listen(window, "resize", () => this.reposition());
    this.listen(document, "scroll", () => this.reposition(), { capture: true });
    this.cleanup(() => this.close());
  }

  toggleOpen(force?: boolean): void {
    const content = this.content();
    if (!content) return;
    const open = force ?? content.hidden;
    content.classList.toggle("show", open);
    setHidden(content, !open);
    this.trigger()?.setAttribute("aria-expanded", String(open));
    if (open) this.reposition();
    else resetFloatingPosition(content);
  }

  close(): void {
    this.toggleOpen(false);
  }

  private reposition(): void {
    const trigger = this.trigger();
    const content = this.content();
    if (!trigger || !content || content.hidden) return;
    const placement = floatingPlacement(this.root.dataset.omPlacement, "bottom-start");
    positionFloatingElement(trigger, content, placement);
  }

  private trigger(): HTMLElement | null {
    return querySelfOrDescendant(this.root, POPOVER_TRIGGER_SELECTOR);
  }

  private content(): HTMLElement | null {
    return querySelfOrDescendant(this.root, POPOVER_CONTENT_SELECTOR);
  }
}
