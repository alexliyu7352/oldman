import { Component } from "../core/component/component";
import { floatingPlacement, positionFloatingElement, resetFloatingPosition } from "../core/dom/floating";
import { querySelfOrDescendant, setHidden } from "../core/dom/helpers";

const TOOLTIP_TRIGGER_SELECTOR = "[data-om-tooltip-trigger]";
const TOOLTIP_CONTENT_SELECTOR = "[data-om-tooltip-content]";
let tooltipId = 0;

/** Show short, non-interactive help text from pointer hover or keyboard focus. */
export class Tooltip extends Component {
  static readonly componentName = "tooltip";
  private focused = false;
  private hovered = false;

  async mount(): Promise<void> {
    const trigger = this.trigger();
    const content = this.content();
    if (!trigger || !content) return;

    if (!content.id) content.id = `om-tooltip-${++tooltipId}`;
    trigger.setAttribute("aria-describedby", content.id);
    setHidden(content, true);

    this.listen(trigger, "mouseenter", () => {
      this.hovered = true;
      this.open();
    });
    this.listen(trigger, "mouseleave", () => {
      this.hovered = false;
      if (!this.focused) this.close();
    });
    this.listen(trigger, "focus", () => {
      this.focused = true;
      this.open();
    });
    this.listen(trigger, "blur", () => {
      this.focused = false;
      if (!this.hovered) this.close();
    });
    this.listen<KeyboardEvent>(document, "keydown", (event) => {
      if (event.key !== "Escape" || content.hidden) return;
      event.stopImmediatePropagation();
      this.hovered = false;
      this.focused = false;
      this.close();
    }, { capture: true });
    this.listen(window, "resize", () => this.reposition());
    this.listen(document, "scroll", () => this.reposition(), { capture: true });
    this.cleanup(() => this.close());
  }

  open(): void {
    const content = this.content();
    if (!content) return;
    content.classList.add("show");
    setHidden(content, false);
    this.reposition();
  }

  close(): void {
    const content = this.content();
    if (!content) return;
    content.classList.remove("show");
    setHidden(content, true);
    resetFloatingPosition(content);
  }

  private reposition(): void {
    const trigger = this.trigger();
    const content = this.content();
    if (!trigger || !content || content.hidden) return;
    const placement = floatingPlacement(this.root.dataset.omPlacement, "top");
    positionFloatingElement(trigger, content, placement);
  }

  private trigger(): HTMLElement | null {
    return querySelfOrDescendant(this.root, TOOLTIP_TRIGGER_SELECTOR);
  }

  private content(): HTMLElement | null {
    return querySelfOrDescendant(this.root, TOOLTIP_CONTENT_SELECTOR);
  }
}
