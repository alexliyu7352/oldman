import type { Page } from "../page/page";
import { queryAllSelfOrDescendants } from "../dom/helpers";
import type { Component, ComponentOptions } from "./component";
import { getOldmanContext } from "../runtime/context";
import { abortError } from "../services/abort";
import {
  ComponentRegistry,
  type ComponentConstructor,
  type NamedComponentConstructor
} from "./registry";

export interface ComponentManagerOptions {
  page?: Page | null;
  registry?: ComponentRegistry;
}

export class ComponentManager {
  private readonly components = new WeakMap<HTMLElement, Component>();
  private readonly roots = new Set<HTMLElement>();
  private readonly childRoots = new Map<HTMLElement, Set<HTMLElement>>();
  private readonly parentRoot = new WeakMap<HTMLElement, HTMLElement>();
  private readonly page: Page | null;
  private readonly registry: ComponentRegistry;

  constructor(options: ComponentManagerOptions = {}) {
    this.page = options.page ?? null;
    this.registry = options.registry ?? getOldmanContext().componentRegistry;
  }

  /**
   * 在当前管理器注册表中注册组件类。
   */
  register(componentClass: NamedComponentConstructor): void;

  /**
   * 使用显式名称在当前管理器注册表中注册组件类。
   */
  register(name: string, componentClass: ComponentConstructor): void;
  register(nameOrClass: string | NamedComponentConstructor, componentClass?: ComponentConstructor): void {
    if (typeof nameOrClass === "string") {
      if (!componentClass) {
        throw new Error(`Component registration for "${nameOrClass}" requires a component class`);
      }

      this.registry.register(nameOrClass, componentClass);
      return;
    }

    this.registry.register(nameOrClass);
  }

  /**
   * 挂载根节点内所有 data-om-component 元素，包含嵌套组件根节点。
   */
  async mount(root: ParentNode): Promise<Component[]> {
    const mounted: Component[] = [];
    const mountedInCall: Component[] = [];

    try {
      await this.mountChildren(root, null, mounted, mountedInCall);
    } catch (error) {
      // Page unmount owns cancellation cleanup, preserving its child/shell order.
      if (this.page?.signal.aborted) throw error;
      const rollbackRoots = mountedInCall.reverse()
        .filter((component) => this.components.get(component.root) === component)
        .map((component) => component.root);
      const rollbackErrors = await this.stopRoots(rollbackRoots);
      if (rollbackErrors.length > 0) {
        throw new AggregateError([error, ...rollbackErrors], "Component manager mount failed");
      }

      throw error;
    }

    return mounted;
  }

  /**
   * 通过根元素或选择器返回已挂载组件实例。
   */
  get<TComponent extends Component = Component>(target: HTMLElement | string): TComponent | null {
    const element = typeof target === "string" ? document.querySelector<HTMLElement>(target) : target;
    if (!element) return null;
    return (this.components.get(element) as TComponent | undefined) ?? null;
  }

  /**
   * 卸载根节点内已挂载组件实例，并保证子组件先于父组件销毁。
   */
  async unmount(root: ParentNode): Promise<void> {
    const roots = this.rootsForUnmount(root);
    const errors = await this.stopRoots(roots);

    if (errors.length === 1) throw errors[0];
    if (errors.length > 1) throw new AggregateError(errors, "Component manager unmount failed");
  }

  /** Unmount mounted components below root while preserving root's own component. */
  async unmountDescendants(root: ParentNode): Promise<void> {
    const roots = this.rootsForUnmount(root).filter((element) => element !== root);
    const errors = await this.stopRoots(roots);
    if (errors.length === 1) throw errors[0];
    if (errors.length > 1) throw new AggregateError(errors, "Component manager descendant unmount failed");
  }

  private async mountChildren(
    root: ParentNode,
    parent: HTMLElement | null,
    mounted: Component[],
    mountedInCall: Component[]
  ): Promise<void> {
    this.page?.signal.throwIfAborted();
    for (const element of immediateComponentRoots(root, parent === null)) {
      this.page?.signal.throwIfAborted();
      const component = await this.mountOne(element, mountedInCall);
      this.page?.signal.throwIfAborted();
      component.signal.throwIfAborted();
      if (this.components.get(element) !== component) throw abortError();
      if (parent) this.trackParent(parent, element);

      mounted.push(component);

      await this.mountChildren(element, element, mounted, mountedInCall);
    }
  }

  /**
   * 创建、跟踪并启动单个组件根节点。
   */
  private async mountOne(element: HTMLElement, mountedInCall: Component[]): Promise<Component> {
    const existing = this.components.get(element);
    if (existing) return existing;

    const componentName = element.dataset.omComponent;
    if (!componentName) throw new Error("Component root is missing data-om-component");

    const ComponentClass = this.registry.resolve(componentName);
    if (!ComponentClass) {
      throw new Error(`No component registered for ${componentName}`);
    }

    const options: ComponentOptions = { page: this.page, manager: this };
    if (this.page) options.i18n = this.page.i18n;
    const component = new ComponentClass(element, options);
    this.components.set(element, component);
    this.roots.add(element);

    try {
      await component.start();
    } catch (error) {
      // A late old start must not unregister a replacement on the same element.
      if (!this.page?.signal.aborted && this.components.get(element) === component) {
        this.unregisterRoot(element);
      }
      throw error;
    }

    mountedInCall.push(component);
    return component;
  }

  private rootsForUnmount(root: ParentNode): HTMLElement[] {
    const roots = new Set<HTMLElement>();

    for (const element of mountedComponentRootsIn(root, this.roots)) {
      collectMountedSubtree(element, this.childRoots, roots);
    }

    return orderChildrenBeforeParents(roots, this.childRoots);
  }

  private async stopRoots(roots: HTMLElement[]): Promise<unknown[]> {
    const errors: unknown[] = [];

    for (const element of roots) {
      const component = this.components.get(element);
      if (!component) continue;

      this.unregisterRoot(element);

      try {
        await component.stop();
      } catch (error) {
        errors.push(error);
      }
    }

    return errors;
  }

  private trackParent(parent: HTMLElement, child: HTMLElement): void {
    const previousParent = this.parentRoot.get(child);
    if (previousParent && previousParent !== parent) {
      this.childRoots.get(previousParent)?.delete(child);
    }

    let children = this.childRoots.get(parent);
    if (!children) {
      children = new Set();
      this.childRoots.set(parent, children);
    }

    children.add(child);
    this.parentRoot.set(child, parent);
  }

  private unregisterRoot(element: HTMLElement): void {
    this.components.delete(element);
    this.roots.delete(element);

    const parent = this.parentRoot.get(element);
    parent && this.childRoots.get(parent)?.delete(element);
    this.parentRoot.delete(element);
    this.childRoots.delete(element);
  }
}

function immediateComponentRoots(root: ParentNode, includeRoot: boolean): HTMLElement[] {
  if (includeRoot && root instanceof Element && root.matches("[data-om-component]")) {
    return [root as HTMLElement];
  }

  const roots = componentRoots(root, includeRoot);

  return roots.filter((element) => {
    const parent = element.parentElement?.closest<HTMLElement>("[data-om-component]") ?? null;
    if (!parent) return true;
    return root instanceof Element && parent === root;
  });
}

function componentRoots(root: ParentNode, includeRoot: boolean): HTMLElement[] {
  if (includeRoot) return queryAllSelfOrDescendants<HTMLElement>(root, "[data-om-component]");
  return Array.from(root.querySelectorAll<HTMLElement>("[data-om-component]"));
}

function mountedComponentRootsIn(root: ParentNode, mountedRoots: Set<HTMLElement>): HTMLElement[] {
  if (root instanceof Document) {
    return Array.from(mountedRoots).filter((element) => element.ownerDocument === root);
  }

  return componentRoots(root, true).filter((element) => mountedRoots.has(element));
}

function collectMountedSubtree(
  element: HTMLElement,
  childRoots: Map<HTMLElement, Set<HTMLElement>>,
  collected: Set<HTMLElement>
): void {
  if (collected.has(element)) return;

  collected.add(element);

  for (const child of childRoots.get(element) ?? []) {
    collectMountedSubtree(child, childRoots, collected);
  }
}

function orderChildrenBeforeParents(
  roots: Set<HTMLElement>,
  childRoots: Map<HTMLElement, Set<HTMLElement>>
): HTMLElement[] {
  const ordered: HTMLElement[] = [];
  const visited = new Set<HTMLElement>();

  for (const root of roots) {
    visit(root, roots, childRoots, visited, ordered);
  }

  return ordered;
}

function visit(
  root: HTMLElement,
  roots: Set<HTMLElement>,
  childRoots: Map<HTMLElement, Set<HTMLElement>>,
  visited: Set<HTMLElement>,
  ordered: HTMLElement[]
): void {
  if (visited.has(root)) return;

  visited.add(root);

  for (const child of childRoots.get(root) ?? []) {
    if (roots.has(child)) visit(child, roots, childRoots, visited, ordered);
  }

  ordered.push(root);
}
