import { maxTimeListMs } from "../core/services/transitions";
import { showResponseActionFailure } from "../core/actions/response-actions";
import { Component, type ComponentOptions } from "../core/component/component";
import { setHidden } from "../core/dom/helpers";
import { isCanceledError } from "../core/services/abort";

export type ModalContent = string | Node | Node[];
export type ModalStatus = "idle" | "loading" | "success" | "error";
export type ModalPartContent = ModalContent | null | undefined;

export interface ModalParts {
  body?: ModalPartContent;
  footer?: ModalPartContent;
  html?: ModalPartContent;
  title?: ModalPartContent;
}

export interface ModalCloseDetail<TModal extends Modal = Modal> {
  component: TModal;
  reason: string;
}

export interface ModalContentDetail<TModal extends Modal = Modal> {
  component: TModal;
  html: string;
  url?: string;
}

export interface ModalPartsDetail<TModal extends Modal = Modal> {
  component: TModal;
  parts: ModalParts;
  url?: string;
}

export interface ModalDestroyDetail<TModal extends Modal = Modal> {
  component: TModal;
}

export interface ModalDynamicContentMountDetail<TModal extends Modal = Modal> {
  component: TModal;
  root: HTMLElement;
  waitUntil(promise: Promise<void>): void;
}

export interface ModalErrorDetail<TModal extends Modal = Modal> {
  component: TModal;
  error: unknown;
  message: string;
  url?: string;
}

export interface ModalOptions extends ComponentOptions {
  backdrop?: boolean;
  backdropClass?: string;
  backdropOpenClass?: string;
  bodyOpenClass?: string;
  closeOnEscape?: boolean;
  closeOnOutside?: boolean;
  contentSelector?: string;
  forceReflowOnOpen?: boolean;
  focusOnOpen?: boolean;
  footerSelector?: string;
  hiddenDisplay?: string;
  openClass?: string;
  restoreFocusOnClose?: boolean;
  statusSelector?: string;
  surfaceSelector?: string;
  titleSelector?: string;
  trapFocus?: boolean;
  transitionElementSelector?: string;
  transitionFallbackMs?: number;
  triggerSelector?: string;
  visibleDisplay?: string;
}

export interface ModalOpenDetail<TModal extends Modal = Modal> {
  component: TModal;
  trigger?: HTMLElement;
}

const MODAL_CONTENT_SELECTOR = "[data-om-modal-content], [role='dialog'], .om-modal";
const MODAL_STATUS_SELECTOR = "[data-om-modal-status]";
const MODAL_TITLE_SELECTOR = "[data-om-modal-title]";
const MODAL_FOOTER_SELECTOR = "[data-om-modal-footer]";
const MODAL_TRIGGER_SELECTOR = "[data-om-modal-target]";
const MODAL_BACKDROP_CLASS = "om-modal-backdrop";
const MODAL_BODY_OPEN_CLASS = "om-modal-open";
const MODAL_FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])"
].join(",");

/**
 * 提供无头弹窗的显示、关闭、内容填充和远程加载能力。
 */
export class Modal extends Component {
  private static openModals: Modal[] = [];
  private readonly backdrop: boolean;
  private readonly backdropClass: string;
  private readonly backdropOpenClass: string | undefined;
  private readonly bodyOpenClass: string;
  private readonly closeOnEscape: boolean;
  private readonly closeOnOutside: boolean;
  private readonly contentSelector: string;
  private readonly forceReflowOnOpen: boolean;
  private readonly focusOnOpen: boolean;
  private readonly footerSelector: string;
  private readonly hiddenDisplay: string | undefined;
  private readonly openClass: string | undefined;
  private readonly restoreFocusOnClose: boolean;
  private readonly statusSelector: string;
  private readonly surfaceSelector: string | undefined;
  private readonly titleSelector: string;
  private readonly trapFocus: boolean;
  private readonly transitionElementSelector: string | undefined;
  private readonly transitionFallbackMs: number;
  private readonly triggerSelector: string;
  private readonly visibleDisplay: string | undefined;
  private backdropElement: HTMLElement | null = null;
  private closeTransitionCleanup: (() => void) | null = null;
  private closeTimerId: number | null = null;
  /** 已经安排、还在等过渡的那次关闭收尾；卸载时要把它跑完，不是取消。 */
  private pendingCloseFinish: (() => void) | null = null;
  private previouslyFocusedElement: HTMLElement | null = null;

  /**
   * 创建弹窗组件，并读取可选的关闭行为和内容区域配置。
   */
  constructor(root: HTMLElement, options: ModalOptions = {}) {
    super(root, options);
    this.backdrop = options.backdrop ?? true;
    this.backdropClass = options.backdropClass ?? MODAL_BACKDROP_CLASS;
    this.backdropOpenClass = options.backdropOpenClass;
    this.bodyOpenClass = options.bodyOpenClass ?? MODAL_BODY_OPEN_CLASS;
    this.closeOnEscape = options.closeOnEscape ?? true;
    this.closeOnOutside = options.closeOnOutside ?? true;
    this.contentSelector = options.contentSelector ?? MODAL_CONTENT_SELECTOR;
    this.forceReflowOnOpen = options.forceReflowOnOpen ?? false;
    this.focusOnOpen = options.focusOnOpen ?? true;
    this.footerSelector = options.footerSelector ?? MODAL_FOOTER_SELECTOR;
    this.hiddenDisplay = options.hiddenDisplay;
    this.openClass = options.openClass;
    this.restoreFocusOnClose = options.restoreFocusOnClose ?? true;
    this.statusSelector = options.statusSelector ?? MODAL_STATUS_SELECTOR;
    this.surfaceSelector = options.surfaceSelector;
    this.titleSelector = options.titleSelector ?? MODAL_TITLE_SELECTOR;
    this.trapFocus = options.trapFocus ?? true;
    this.transitionElementSelector = options.transitionElementSelector;
    this.transitionFallbackMs = options.transitionFallbackMs ?? 0;
    this.triggerSelector = options.triggerSelector ?? MODAL_TRIGGER_SELECTOR;
    this.visibleDisplay = options.visibleDisplay;
  }

  /**
   * 注册关闭按钮、Escape 键和点击弹窗外部关闭的基础行为。
   */
  async mount(): Promise<void> {
    if (this.root.hidden) this.applyClosedVisualState();

    this.listen<MouseEvent>(document, "click", (event) => {
      const trigger = this.triggerFromEvent(event);
      if (!trigger) return;

      event.preventDefault();
      // 声明式点击由此入口显示失败；直接调用 loadParts/loadContent 仍由调用方处理。
      void this.openFromTrigger(trigger).catch((error: unknown) => {
        if (this.signal.aborted || isCanceledError(error)) return;
        if (this.page) return showResponseActionFailure(this.page, trigger, error);
        this.logger.error("Oldman modal loading failed", error);
      });
    });

    this.on("click", "[data-om-modal-close]", (event) => {
      event.preventDefault();
      this.close("dismiss");
    });

    this.listen<KeyboardEvent>(document, "keydown", (event) => {
      if (!this.isTopmostOpenModal()) return;

      if (this.trapFocus && event.key === "Tab") {
        this.trapTabFocus(event);
        return;
      }

      if (this.closeOnEscape && event.key === "Escape" && this.isOpen()) {
        this.close("escape");
      }
    });

    this.listen<MouseEvent>(this.root, "click", (event) => {
      if (this.closeOnOutside && this.isOutsideClick(event)) {
        this.close("outside");
      }
    });

    this.cleanup(() => this.cleanupOpenState());
  }

  /**
   * 显示弹窗根节点，并派发 `om:modal:open` 事件供外部监听。
   */
  open(trigger?: HTMLElement): void {
    this.clearPendingCloseTransition();
    const wasOpen = this.isOpen();
    if (!wasOpen) {
      this.previouslyFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    this.root.classList.remove("hidden");
    setHidden(this.root, false);
    this.root.setAttribute("role", this.root.getAttribute("role") || "dialog");
    this.root.setAttribute("aria-modal", "true");
    this.root.setAttribute("aria-hidden", "false");
    this.root.dataset.omState = "open";
    if (!wasOpen) {
      this.showBackdrop();
    }
    this.registerOpenModal();
    this.applyOpenVisualState();
    if (this.focusOnOpen) this.focusInitialElement();
    const detail: ModalOpenDetail = trigger ? { component: this, trigger } : { component: this };
    this.emit<ModalOpenDetail>("om:modal:open", detail);
  }

  /**
   * 隐藏弹窗根节点，并携带关闭原因派发 `om:modal:close` 事件。
   */
  close(reason = "programmatic"): void {
    if (this.closeTimerId !== null) return;

    const wasOpen = this.isOpen();
    this.root.dataset.omState = "closing";
    const durationMs = wasOpen ? this.applyClosingVisualState() : 0;
    const finish = () => this.finishClose(reason, wasOpen);

    if (durationMs <= 0) {
      finish();
      return;
    }

    this.scheduleCloseAfterTransition(durationMs, finish);
  }

  /**
   * 将本地内容写入弹窗内容区域。
   */
  setContent(content: ModalContent): void {
    const target = this.contentContainer();
    if (!target) return;

    if (typeof content === "string") {
      target.innerHTML = content;
      return;
    }

    if (Array.isArray(content)) {
      target.replaceChildren(...content);
      return;
    }

    target.replaceChildren(content);
  }

  /**
   * 按标题、主体和底部片段更新弹窗，不破坏外层容器和已绑定事件。
   */
  setParts(parts: ModalParts): void {
    if ("title" in parts) this.setOptionalPart(this.titleElement(), parts.title);
    if ("body" in parts || "html" in parts) this.setOptionalPart(this.contentContainer(), parts.body ?? parts.html);
    if ("footer" in parts) this.setOptionalPart(this.footerElement(), parts.footer);
    this.emit<ModalPartsDetail>("om:modal:parts", { component: this, parts });
  }

  /**
   * 从远程 JSON 载入弹窗片段，适用于后端一次返回标题、表单和按钮区的场景。
   */
  async loadParts(url: string): Promise<ModalParts> {
    this.setStatus("loading", this.i18n.t("Loading..."));

    try {
      const parts = await this.http.getJson<ModalParts>(url);
      const targets: Array<HTMLElement | null> = [];
      if ("title" in parts) targets.push(this.titleElement());
      if ("body" in parts || "html" in parts) targets.push(this.contentContainer());
      if ("footer" in parts) targets.push(this.footerElement());
      await this.unmountDynamicContent(targets);
      this.setParts(parts);
      await this.mountDynamicContent();
      this.setStatus("success");
      this.emit<ModalPartsDetail>("om:modal:parts", { component: this, parts, url });
      return parts;
    } catch (error) {
      const message = this.errorMessage(error);
      this.setStatus("error", message);
      this.emit<ModalErrorDetail>("om:modal:error", { component: this, error, message, url });
      throw error;
    }
  }

  /**
   * 从远程地址加载 HTML 片段，并写入弹窗内容区域。
   */
  async loadContent(url: string): Promise<string> {
    this.setStatus("loading", this.i18n.t("Loading..."));

    try {
      const html = await this.http.html(url);
      await this.unmountDynamicContent([this.contentContainer()]);
      this.setContent(html);
      await this.mountDynamicContent();
      this.setStatus("success");
      this.emit<ModalContentDetail>("om:modal:content", { component: this, html, url });
      return html;
    } catch (error) {
      const message = this.errorMessage(error);
      this.setStatus("error", message);
      this.emit<ModalErrorDetail>("om:modal:error", { component: this, error, message, url });
      throw error;
    }
  }

  /**
   * 更新弹窗状态，并同步可选状态文本元素。
   */
  setStatus(status: ModalStatus, message = ""): void {
    this.root.dataset.omStatus = status;

    const statusElement = this.statusElement();
    if (!statusElement) return;

    statusElement.textContent = message;
    statusElement.hidden = status === "success" || status === "idle" || message.length === 0;
  }

  /**
   * 关闭弹窗、派发销毁事件，并停止组件生命周期。
   */
  async destroy(): Promise<void> {
    if (this.isOpen()) {
      this.close("destroy");
    }

    this.emit<ModalDestroyDetail>("om:modal:destroy", { component: this });
    await this.stop();
  }

  /**
   * 判断弹窗当前是否处于可见状态。
   */
  private isOpen(): boolean {
    return !this.root.hidden;
  }

  /**
   * 应用打开时的视觉状态；主题适配子类可覆写此方法接入自定义动画。
   */
  protected applyOpenVisualState(): void {
    if (this.visibleDisplay !== undefined) this.root.style.display = this.visibleDisplay;

    if (this.forceReflowOnOpen) {
      // 强制浏览器提交打开前的初始状态，避免 display 和 open class 同帧写入跳过 CSS 过渡。
      void this.root.offsetHeight;
    }

    if (this.openClass) this.root.classList.add(this.openClass);
    this.setBackdropOpenClass(true);
  }

  /**
   * 应用关闭过渡的起始视觉状态，并返回需要等待的过渡时长。
   */
  protected applyClosingVisualState(): number {
    if (this.openClass) this.root.classList.remove(this.openClass);
    this.setBackdropOpenClass(false);
    return this.modalTransitionDurationMs();
  }

  /**
   * 应用完全关闭后的视觉状态；默认只处理配置项声明的样式。
   */
  protected applyClosedVisualState(): void {
    if (this.openClass) this.root.classList.remove(this.openClass);
    if (this.hiddenDisplay !== undefined) this.root.style.display = this.hiddenDisplay;
  }

  /**
   * 获取当前弹窗创建的遮罩节点，供主题适配子类读取或扩展。
   */
  protected currentBackdropElement(): HTMLElement | null {
    return this.backdropElement;
  }

  /**
   * 从点击事件中解析属于当前弹窗的声明式触发按钮。
   */
  private triggerFromEvent(event: MouseEvent): HTMLElement | null {
    const target = event.target;
    if (!(target instanceof Element)) return null;

    const trigger = target.closest<HTMLElement>(this.triggerSelector);
    const selector = trigger?.getAttribute("data-om-modal-target");
    if (!trigger || !selector || !this.matchesModalSelector(selector)) return null;
    return trigger;
  }

  /**
   * 通过声明式按钮打开弹窗，并按需先加载远程片段。
   */
  private async openFromTrigger(trigger: HTMLElement): Promise<void> {
    const url = trigger.getAttribute("data-om-modal-url");
    if (url) {
      await this.loadParts(url);
    }
    this.open(trigger);
  }

  /**
   * 判断声明式选择器是否指向当前弹窗根节点。
   */
  private matchesModalSelector(selector: string): boolean {
    try {
      return this.root.matches(selector);
    } catch {
      return false;
    }
  }

  /**
   * 远程内容写入后挂载新增的声明式子组件，例如弹窗内表单校验器。
   */
  private async mountDynamicContent(): Promise<void> {
    const pending: Promise<void>[] = [];
    this.emit<ModalDynamicContentMountDetail>("om:component:before-dynamic-content-mount", {
      component: this,
      root: this.root,
      waitUntil(promise: Promise<void>) {
        pending.push(promise);
      }
    });
    await Promise.all(pending);
    await this.manager?.mount(this.root);
  }

  /** 远程片段覆盖 DOM 前先卸载其中已有的组件。 */
  private async unmountDynamicContent(targets: Array<HTMLElement | null>): Promise<void> {
    for (const target of new Set(targets)) {
      if (target) await this.manager?.unmountDescendants(target);
    }
  }

  /**
   * 判断点击事件是否发生在弹窗内容区域外部。
   */
  private isOutsideClick(event: MouseEvent): boolean {
    const target = event.target;
    if (!(target instanceof Node)) return false;
    if (target === this.root) return true;

    const surface = this.surfaceElement() ?? this.contentContainer();
    return Boolean(surface && !surface.contains(target));
  }

  /**
   * 获取弹窗主体内容容器。
   */
  private contentContainer(): HTMLElement | null {
    if (this.root.matches(this.contentSelector)) return this.root;
    return this.root.querySelector<HTMLElement>(this.contentSelector);
  }

  /**
   * 获取用于判断外部点击的弹窗表面容器。
   */
  private surfaceElement(): HTMLElement | null {
    if (!this.surfaceSelector) return null;
    if (this.root.matches(this.surfaceSelector)) return this.root;
    return this.root.querySelector<HTMLElement>(this.surfaceSelector);
  }

  /**
   * 获取弹窗底部容器。
   */
  private footerElement(): HTMLElement | null {
    return this.root.querySelector<HTMLElement>(this.footerSelector);
  }

  /**
   * 获取弹窗状态提示元素。
   */
  private statusElement(): HTMLElement | null {
    return this.root.querySelector<HTMLElement>(this.statusSelector);
  }

  /**
   * 获取弹窗标题容器。
   */
  private titleElement(): HTMLElement | null {
    return this.root.querySelector<HTMLElement>(this.titleSelector);
  }

  /**
   * 按空值规则写入可选区域，并同步隐藏状态。
   */
  private setOptionalPart(target: HTMLElement | null, content: ModalPartContent): void {
    if (!target) return;

    if (content === null || content === undefined || content === "") {
      target.replaceChildren();
      target.hidden = true;
      return;
    }

    target.hidden = false;
    this.replacePartContent(target, content);
  }

  /**
   * 将字符串或 DOM 节点替换到指定弹窗区域。
   */
  private replacePartContent(target: HTMLElement, content: ModalContent): void {
    if (typeof content === "string") {
      target.innerHTML = content;
      return;
    }

    if (Array.isArray(content)) {
      target.replaceChildren(...content);
      return;
    }

    target.replaceChildren(content);
  }

  /**
   * 创建并显示弹窗遮罩层。
   */
  private showBackdrop(): void {
    if (!this.backdrop || this.backdropElement) return;

    const backdrop = document.createElement("div");
    backdrop.dataset.omModalBackdrop = "true";
    backdrop.className = this.backdropClass;
    backdrop.addEventListener("click", () => {
      if (this.closeOnOutside) this.close("backdrop");
    });
    document.body.append(backdrop);
    this.backdropElement = backdrop;
    this.syncBackdropGeometry();
  }

  /**
   * 移除当前弹窗创建的遮罩层。
   */
  private hideBackdrop(): void {
    this.backdropElement?.remove();
    this.backdropElement = null;
  }

  /**
   * 同步遮罩层的打开态 class，适配带过渡效果的主题。
   */
  private setBackdropOpenClass(open: boolean): void {
    if (!this.backdropOpenClass || !this.backdropElement) return;
    this.backdropElement.classList.toggle(this.backdropOpenClass, open);
  }

  /**
   * Playwright full-page captures include document area below the viewport; keep the overlay covering both.
   */
  private syncBackdropGeometry(): void {
    if (!this.backdropElement) return;

    const height = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight, window.innerHeight);
    this.backdropElement.style.minHeight = `${height}px`;
  }

  /**
   * 记录打开顺序并锁定页面滚动，使键盘只作用于最上层弹窗。
   */
  private registerOpenModal(): void {
    Modal.openModals = Modal.openModals.filter((modal) => modal !== this);
    Modal.openModals.push(this);
    document.body.classList.add(this.bodyOpenClass);
  }

  /**
   * 移除当前弹窗，直到同类滚动锁的最后一个弹窗关闭才移除 body class。
   */
  private unregisterOpenModal(): void {
    Modal.openModals = Modal.openModals.filter((modal) => modal !== this);
    if (!Modal.openModals.some((modal) => modal.bodyOpenClass === this.bodyOpenClass)) {
      document.body.classList.remove(this.bodyOpenClass);
    }
  }

  private isTopmostOpenModal(): boolean {
    return this.isOpen() && Modal.openModals.at(-1) === this;
  }

  /**
   * 生命周期结束时清理仍然打开的弹窗副作用。
   */
  private cleanupOpenState(): void {
    // 还有一次关闭在等过渡时，要把它**跑完**，不能取消。
    // `destroy()` 是 close() + stop()，而 stop() 的清理走到这里：取消掉那个定时器就等于
    // finishClose 永远不执行，面板留在屏幕上、状态卡在 `closing`、aria-modal 还宣称自己是
    // 打开的对话框，而组件已经停止、所有关闭入口都失效了。
    // 没有 CSS 过渡的弹窗恰好躲过这一点，而那才是现实中少见的情况。
    const finishPendingClose = this.pendingCloseFinish;
    if (finishPendingClose) {
      // finishClose() 内部会调用 clearPendingCloseTransition()，收尾一并完成。
      finishPendingClose();
    } else {
      this.clearPendingCloseTransition();
    }

    if (this.isOpen()) {
      this.hideBackdrop();
      this.unregisterOpenModal();
    }
  }

  /**
   * 将 Tab/Shift+Tab 焦点循环限制在弹窗内部。
   */
  private trapTabFocus(event: KeyboardEvent): void {
    const focusableElements = this.focusableElements();
    if (focusableElements.length === 0) {
      event.preventDefault();
      this.focusFallbackElement();
      return;
    }

    const first = focusableElements[0] as HTMLElement;
    const last = focusableElements[focusableElements.length - 1] as HTMLElement;
    const activeElement = document.activeElement;
    if (event.shiftKey && activeElement === first) {
      event.preventDefault();
      last.focus();
      return;
    }

    if (!event.shiftKey && activeElement === last) {
      event.preventDefault();
      first.focus();
      return;
    }

    if (!(activeElement instanceof Node) || !this.root.contains(activeElement)) {
      event.preventDefault();
      first.focus();
    }
  }

  /**
   * 弹窗打开后聚焦第一个可交互元素，缺失时聚焦内容容器。
   */
  private focusInitialElement(): void {
    const focusable = this.focusableElements()[0];
    if (focusable) {
      focusable.focus();
      return;
    }

    this.focusFallbackElement();
  }

  /**
   * 获取弹窗内部当前可参与键盘导航的元素。
   */
  private focusableElements(): HTMLElement[] {
    return Array.from(this.root.querySelectorAll<HTMLElement>(MODAL_FOCUSABLE_SELECTOR)).filter((element) => {
      return !element.hidden && element.getAttribute("aria-hidden") !== "true";
    });
  }

  /**
   * 没有可交互元素时，聚焦内容容器或弹窗根节点。
   */
  private focusFallbackElement(): void {
    const target = this.contentContainer() ?? this.root;
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.focus();
  }

  /**
   * 弹窗关闭后把焦点还原到打开前的元素。
   */
  private restorePreviousFocus(): void {
    if (!this.previouslyFocusedElement || !document.contains(this.previouslyFocusedElement)) return;

    this.previouslyFocusedElement.focus();
    this.previouslyFocusedElement = null;
  }

  /**
   * 完成关闭流程，统一处理隐藏、遮罩、滚动锁、焦点还原和关闭事件。
   */
  private finishClose(reason: string, wasOpen: boolean): void {
    this.clearPendingCloseTransition();
    setHidden(this.root, true);
    this.root.classList.add("hidden");
    this.root.setAttribute("aria-hidden", "true");
    this.root.removeAttribute("aria-modal");
    this.root.dataset.omState = "closed";
    this.applyClosedVisualState();
    if (wasOpen) {
      this.hideBackdrop();
      this.unregisterOpenModal();
    }
    if (this.restoreFocusOnClose) this.restorePreviousFocus();
    this.emit<ModalCloseDetail>("om:modal:close", { component: this, reason });
  }

  /**
   * 根据配置的过渡元素等待 transitionend，超时时使用兜底计时器完成关闭。
   */
  private scheduleCloseAfterTransition(durationMs: number, finish: () => void): void {
    let finished = false;
    const startedAt = performance.now();
    const transitionElement = this.transitionElement();
    const done = () => {
      if (finished) return;
      finished = true;
      finish();
    };
    this.pendingCloseFinish = done;

    const onEnd = (event: Event) => {
      // 部分主题或嵌套弹窗会产生很早的 transitionend，必须等到声明的过渡时间后再真正隐藏。
      if (performance.now() - startedAt < durationMs - 16) return;
      if (event.target === transitionElement) done();
    };

    if (transitionElement) {
      transitionElement.addEventListener("transitionend", onEnd);
      transitionElement.addEventListener("transitioncancel", onEnd);
      transitionElement.addEventListener("animationend", onEnd);
      transitionElement.addEventListener("animationcancel", onEnd);
      this.closeTransitionCleanup = () => {
        transitionElement.removeEventListener("transitionend", onEnd);
        transitionElement.removeEventListener("transitioncancel", onEnd);
        transitionElement.removeEventListener("animationend", onEnd);
        transitionElement.removeEventListener("animationcancel", onEnd);
      };
    }

    // 浏览器节流动画时可能不派发 transitionend，因此在声明时长后的下一帧兜底关闭。
    this.closeTimerId = this.timers.timeout(done, durationMs + 16);
  }

  /**
   * 清理尚未完成的关闭过渡监听和兜底计时器。
   */
  private clearPendingCloseTransition(): void {
    if (this.closeTimerId !== null) {
      window.clearTimeout(this.closeTimerId);
      this.closeTimerId = null;
    }

    this.pendingCloseFinish = null;
    this.closeTransitionCleanup?.();
    this.closeTransitionCleanup = null;
  }

  /**
   * 解析需要监听过渡结束事件的元素。
   */
  private transitionElement(): HTMLElement | null {
    if (!this.transitionElementSelector) return this.root;
    if (this.root.matches(this.transitionElementSelector)) return this.root;
    return this.root.querySelector<HTMLElement>(this.transitionElementSelector);
  }

  /**
   * 读取弹窗过渡时长，缺少 CSS 过渡时回退到配置的兜底时间。
   */
  private modalTransitionDurationMs(): number {
    const element = this.transitionElement();
    if (!element) return this.transitionFallbackMs;

    const style = window.getComputedStyle?.(element);
    if (!style) return this.transitionFallbackMs;

    const durationMs = Math.max(
      maxTimeListMs(style.transitionDuration, style.transitionDelay),
      maxTimeListMs(style.animationDuration, style.animationDelay)
    );
    return durationMs > 0 ? durationMs : this.transitionFallbackMs;
  }

  /**
   * 将未知错误转换为可展示的错误文案。
   */
  private errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : this.i18n.t("Request failed");
  }
}
