import { afterEach, describe, expect, it, vi } from "vitest";
import type { DefaultApiResponse } from "../core/actions/response-actions";
import type { ComponentRunActionOptions } from "../core/component/component";
import { SortableList } from "./sortable-list";

interface SortableOptionsProbe {
  disabled?: boolean;
  group?: string;
  handle?: string;
  onEnd?: (event: SortableEventProbe) => void | Promise<void>;
}

interface SortableEventProbe {
  from: HTMLElement;
  item: HTMLElement;
  newIndex?: number;
  oldIndex?: number;
  to: HTMLElement;
}

const sortableState = vi.hoisted(() => ({
  instances: [] as Array<{
    destroy: ReturnType<typeof vi.fn>;
    element: HTMLElement;
    option: ReturnType<typeof vi.fn>;
    options: SortableOptionsProbe;
  }>
}));

vi.mock("sortablejs", () => ({
  default: class SortableMock {
    readonly destroy = vi.fn();
    readonly option = vi.fn((name: string, value?: unknown) => {
      if (value !== undefined) this.options[name as keyof SortableOptionsProbe] = value as never;
      return this.options[name as keyof SortableOptionsProbe];
    });

    constructor(readonly element: HTMLElement, readonly options: SortableOptionsProbe) {
      sortableState.instances.push(this);
    }
  }
}));

const successResponse: DefaultApiResponse = { actions: [], data: {}, error_code: 0, message: "" };
const rejectedResponse: DefaultApiResponse = { actions: [], data: {}, error_code: 1, message: "Rejected" };

class TestSortableList extends SortableList {
  readonly calls: ComponentRunActionOptions[] = [];
  responses: Array<DefaultApiResponse | null | Promise<DefaultApiResponse | null>> = [successResponse];

  override runAction(_trigger: HTMLElement, options: ComponentRunActionOptions = {}) {
    this.calls.push(options);
    return Promise.resolve(this.responses.length > 0 ? this.responses.shift()! : successResponse);
  }
}

function markup(): string {
  return `
    <section
      data-om-component="sortable-list"
      data-om-sortable-group="review"
      data-om-sortable-url="/tasks/move"
    >
      <div data-om-sortable-list data-om-list-id="todo">
        <article data-om-sortable-item data-om-item-id="task-1"><button data-om-sortable-handle>Move</button></article>
        <article data-om-sortable-item data-om-item-id="task-2"><button data-om-sortable-handle>Move</button></article>
      </div>
      <div data-om-sortable-list data-om-list-id="done">
        <article data-om-sortable-item data-om-item-id="task-3"><button data-om-sortable-handle>Move</button></article>
      </div>
    </section>
  `;
}

function setup(): { component: TestSortableList; lists: HTMLElement[] } {
  document.body.innerHTML = markup();
  const component = new TestSortableList(document.querySelector<HTMLElement>("[data-om-component='sortable-list']")!);
  const lists = Array.from(document.querySelectorAll<HTMLElement>("[data-om-sortable-list]"));
  return { component, lists };
}

async function move(
  instanceIndex: number,
  item: HTMLElement,
  from: HTMLElement,
  to: HTMLElement,
  oldIndex: number,
  newIndex: number
): Promise<void> {
  const reference = to.querySelectorAll<HTMLElement>("[data-om-sortable-item]").item(newIndex);
  to.insertBefore(item, reference || null);
  await sortableState.instances[instanceIndex]!.options.onEnd?.({ from, item, newIndex, oldIndex, to });
}

describe("SortableList", () => {
  afterEach(() => {
    document.body.replaceChildren();
    sortableState.instances = [];
    vi.restoreAllMocks();
  });

  it("为同一组列表创建 SortableJS 实例并在卸载时销毁", async () => {
    const { component } = setup();

    await component.start();

    expect(sortableState.instances).toHaveLength(2);
    expect(sortableState.instances.map(({ options }) => options.group)).toEqual(["review", "review"]);
    expect(sortableState.instances.map(({ options }) => options.handle)).toEqual([
      "[data-om-sortable-handle]",
      "[data-om-sortable-handle]"
    ]);
    const trigger = document.querySelector<HTMLButtonElement>("[data-om-action='post']")!;
    expect(trigger.hidden).toBe(true);
    expect(trigger.dataset.omUrl).toBe("/tasks/move");

    await component.stop();
    expect(sortableState.instances.every(({ destroy }) => destroy.mock.calls.length === 1)).toBe(true);
    expect(trigger.isConnected).toBe(false);
  });

  it("提交同列和跨列移动意图，成功后保留新位置", async () => {
    const { component, lists } = setup();
    await component.start();
    const [todo, done] = lists as [HTMLElement, HTMLElement];
    const task2 = todo.querySelectorAll<HTMLElement>("[data-om-sortable-item]").item(1);

    await move(0, task2, todo, todo, 1, 0);
    expect(component.calls[0]?.params).toEqual({
      item_id: "task-2",
      source_list: "todo",
      target_list: "todo",
      target_position: "0"
    });
    expect(todo.firstElementChild).toBe(task2);

    component.responses.push(successResponse);
    await move(0, task2, todo, done, 0, 1);
    expect(component.calls[1]?.params).toEqual({
      item_id: "task-2",
      source_list: "todo",
      target_list: "done",
      target_position: "1"
    });
    expect(done.lastElementChild).toBe(task2);

    await component.stop();
  });

  it.each([
    ["业务拒绝", rejectedResponse],
    ["网络失败", null]
  ])("%s 时把同一个节点放回原列表和位置", async (_name, response) => {
    const { component, lists } = setup();
    component.responses = [response];
    await component.start();
    const [todo, done] = lists as [HTMLElement, HTMLElement];
    const task2 = todo.querySelectorAll<HTMLElement>("[data-om-sortable-item]").item(1);

    await move(0, task2, todo, done, 1, 1);

    expect(todo.lastElementChild).toBe(task2);
    expect(done.contains(task2)).toBe(false);
    await component.stop();
  });

  it("请求期间禁用全部列表并拒绝重复提交", async () => {
    const { component, lists } = setup();
    let resolve!: (response: DefaultApiResponse) => void;
    component.responses = [new Promise((done) => { resolve = done; })];
    await component.start();
    const [todo, done] = lists as [HTMLElement, HTMLElement];
    const task1 = todo.firstElementChild as HTMLElement;

    const pending = move(0, task1, todo, done, 0, 1);
    await Promise.resolve();

    expect(component.calls).toHaveLength(1);
    expect(sortableState.instances.every(({ option }) => option.mock.calls.some((call) => call[0] === "disabled" && call[1] === true))).toBe(true);

    resolve(successResponse);
    await pending;
    expect(sortableState.instances.every(({ option }) => option.mock.calls.at(-1)?.[1] === false)).toBe(true);
    await component.stop();
  });
});
