import Sortable from "sortablejs";
import type { SortableEvent } from "sortablejs";
import "./sortable-list.scss";
import { Component, type ComponentOptions } from "../core/component/component";

const LIST_SELECTOR = "[data-om-sortable-list]";
const ITEM_SELECTOR = "[data-om-sortable-item]";
const DEFAULT_HANDLE_SELECTOR = "[data-om-sortable-handle]";

export interface SortableListOptions extends ComponentOptions {
  group?: string;
  handle?: string | null;
}

export interface SortableMoveIntent {
  itemId: string;
  sourceList: string;
  targetList: string;
  targetPosition: number;
}

/**
 * 管理同一分组中的平面拖拽列表，并通过标准 data action 提交移动意图。
 */
export class SortableList extends Component {
  static readonly componentName = "sortable-list";
  private readonly configuredGroup: string | undefined;
  private readonly configuredHandle: string | null | undefined;
  private instances: Sortable[] = [];
  private pending = false;
  private actionTrigger: HTMLButtonElement | null = null;

  constructor(root: HTMLElement, options: SortableListOptions = {}) {
    super(root, options);
    this.configuredGroup = options.group;
    this.configuredHandle = options.handle;
  }

  /** 初始化当前组件中的全部列表。 */
  override async mount(): Promise<void> {
    const group = this.configuredGroup ?? this.root.dataset.omSortableGroup;
    if (!group) throw new Error("SortableList requires data-om-sortable-group");
    const url = this.root.dataset.omSortableUrl;
    if (!url) throw new Error("SortableList requires data-om-sortable-url");

    const lists = Array.from(this.root.querySelectorAll<HTMLElement>(LIST_SELECTOR));
    if (lists.length === 0) throw new Error("SortableList requires at least one data-om-sortable-list");
    for (const list of lists) this.validateList(list);

    this.actionTrigger = this.root.ownerDocument.createElement("button");
    this.actionTrigger.type = "button";
    this.actionTrigger.hidden = true;
    this.actionTrigger.dataset.omAction = this.root.dataset.omSortableAction || "post";
    this.actionTrigger.dataset.omUrl = url;
    this.root.append(this.actionTrigger);

    const handle = this.configuredHandle === undefined
      ? this.root.dataset.omSortableHandle || DEFAULT_HANDLE_SELECTOR
      : this.configuredHandle;
    this.instances = lists.map((list) => new Sortable(list, {
      animation: 150,
      chosenClass: "om-sortable-chosen",
      dataIdAttr: "data-om-item-id",
      dragClass: "om-sortable-drag",
      draggable: ITEM_SELECTOR,
      fallbackOnBody: true,
      ghostClass: "om-sortable-ghost",
      group,
      ...(handle ? { handle } : {}),
      onEnd: (event) => this.handleEnd(event)
    }));
  }

  /** 销毁 SortableJS 实例，避免 Turbo 页面切换后遗留监听器。 */
  override async unmount(): Promise<void> {
    for (const instance of this.instances) instance.destroy();
    this.instances = [];
    this.actionTrigger?.remove();
    this.actionTrigger = null;
  }

  private async handleEnd(event: SortableEvent): Promise<void> {
    const oldIndex = event.oldDraggableIndex ?? event.oldIndex;
    const newIndex = event.newDraggableIndex ?? event.newIndex;
    if (oldIndex === undefined || newIndex === undefined) return;
    if (event.from === event.to && oldIndex === newIndex) return;
    if (this.pending) {
      this.restore(event.item, event.from, oldIndex);
      return;
    }

    this.pending = true;
    this.setDisabled(true);
    try {
      const intent = this.moveIntent(event, newIndex);
      if (!this.actionTrigger) throw new Error("SortableList is not mounted");
      const response = await this.runAction(this.actionTrigger, {
        params: {
          item_id: intent.itemId,
          source_list: intent.sourceList,
          target_list: intent.targetList,
          target_position: String(intent.targetPosition)
        }
      });
      if (!response || response.error_code !== 0) this.restore(event.item, event.from, oldIndex);
    } catch (error) {
      this.restore(event.item, event.from, oldIndex);
      if (!this.signal.aborted) this.logger.error("SortableList move failed", error);
    } finally {
      this.pending = false;
      if (!this.signal.aborted) this.setDisabled(false);
    }
  }

  private moveIntent(event: SortableEvent, targetPosition: number): SortableMoveIntent {
    const itemId = event.item.dataset.omItemId;
    const sourceList = event.from.dataset.omListId;
    const targetList = event.to.dataset.omListId;
    if (!itemId || !sourceList || !targetList) {
      throw new Error("SortableList items and lists require stable IDs");
    }
    return { itemId, sourceList, targetList, targetPosition };
  }

  private restore(item: HTMLElement, list: HTMLElement, index: number): void {
    const items = Array.from(list.querySelectorAll<HTMLElement>(`:scope > ${ITEM_SELECTOR}`)).filter(
      (candidate) => candidate !== item
    );
    const reference = items[index];
    if (reference) {
      list.insertBefore(item, reference);
    } else if (items.length > 0) {
      items.at(-1)!.after(item);
    } else {
      list.prepend(item);
    }
  }

  private setDisabled(disabled: boolean): void {
    this.root.toggleAttribute("data-om-sortable-pending", disabled);
    for (const instance of this.instances) instance.option("disabled", disabled);
  }

  private validateList(list: HTMLElement): void {
    if (!list.dataset.omListId) throw new Error("SortableList lists require data-om-list-id");
    for (const item of list.querySelectorAll<HTMLElement>(`:scope > ${ITEM_SELECTOR}`)) {
      if (!item.dataset.omItemId) throw new Error("SortableList items require data-om-item-id");
    }
  }
}
