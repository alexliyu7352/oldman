import { Component } from "../core/component/component";
import { floatingPlacement, positionFloatingElement, resetFloatingPosition } from "../core/dom/floating";
import { querySelfOrDescendant, setHidden } from "../core/dom/helpers";

const TOOLTIP_TRIGGER_SELECTOR = "[data-om-tooltip-trigger]";
const TOOLTIP_CONTENT_SELECTOR = "[data-om-tooltip-content]";
const DEFAULT_HOVER_DELAY_MS = 200;
let tooltipId = 0;

/** Show short, non-interactive help text from pointer hover (after a short delay) or keyboard focus. */
export class Tooltip extends Component {
  static readonly componentName = "tooltip";
  private focused = false;
  private hovered = false;
  private hoverTimer: number | null = null;
  private contentElement: HTMLElement | null = null;
  /** Marks where the content lives in the template so it can return after being portaled to <body>. */
  private contentAnchor: Comment | null = null;

  async mount(): Promise<void> {
    const trigger = this.trigger();
    const content = this.content();
    if (!trigger || !content) return;
    this.contentElement = content;

    if (!content.id) content.id = `om-tooltip-${++tooltipId}`;
    trigger.setAttribute("aria-describedby", content.id);
    setHidden(content, true);

    this.listen(trigger, "mouseenter", () => {
      this.hovered = true;
      this.scheduleOpen();
    });
    this.listen(trigger, "mouseleave", () => {
      this.hovered = false;
      this.cancelScheduledOpen();
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
      this.cancelScheduledOpen();
      this.close();
    }, { capture: true });
    this.listen(window, "resize", () => this.reposition());
    // 捕获阶段监听 document 的滚动是必要的:浮层锚定在触发元素上,而滚动可能发生在任何
    // 祖先容器里,冒泡阶段收不到。不是性能问题:`scroll` 事件本来就不可取消,passive 与否
    // 对它没有意义;`reposition()` 第一件事是判断是否打开,关闭时直接返回。
    this.listen(document, "scroll", () => this.reposition(), { capture: true });
    this.cleanup(() => {
      this.cancelScheduledOpen();
      this.close();
      this.contentElement = null;
    });
  }

  /** Pointer hover waits `data-om-delay` ms (default 200) so passing the cursor over a row stays quiet. */
  private scheduleOpen(): void {
    this.cancelScheduledOpen();
    const delay = this.hoverDelay();
    if (delay <= 0) {
      this.open();
      return;
    }
    this.hoverTimer = window.setTimeout(() => {
      this.hoverTimer = null;
      if (this.hovered) this.open();
    }, delay);
  }

  private cancelScheduledOpen(): void {
    if (this.hoverTimer === null) return;
    window.clearTimeout(this.hoverTimer);
    this.hoverTimer = null;
  }

  private hoverDelay(): number {
    const value = Number(this.root.dataset.omDelay);
    return Number.isFinite(value) && this.root.dataset.omDelay !== undefined ? Math.max(0, value) : DEFAULT_HOVER_DELAY_MS;
  }

  open(): void {
    const content = this.content();
    if (!content) return;
    this.portalContent(content);
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
    this.restoreContent(content);
  }

  /**
   * Render the bubble from <body>: a transformed, clipped or `contain: paint` ancestor (sidebar,
   * table cell, card) would otherwise become the containing block and squeeze or clip it.
   */
  private portalContent(content: HTMLElement): void {
    if (content.parentElement === document.body) return;
    if (!this.contentAnchor) this.contentAnchor = document.createComment("om-tooltip");
    content.before(this.contentAnchor);
    document.body.append(content);
  }

  private restoreContent(content: HTMLElement): void {
    const anchor = this.contentAnchor;
    if (!anchor || !anchor.parentNode || content.parentElement !== document.body) return;
    anchor.parentNode.insertBefore(content, anchor);
    anchor.remove();
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
    return this.contentElement ?? querySelfOrDescendant(this.root, TOOLTIP_CONTENT_SELECTOR);
  }
}
