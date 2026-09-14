import type { Component, ComponentOptions } from "./component";

export type ComponentState = "created" | "mounting" | "mounted" | "unmounting" | "unmounted" | "failed";

export interface ComponentConstructor<TComponent extends Component = Component> {
  new (root: HTMLElement, options?: ComponentOptions): TComponent;
}

export interface NamedComponentConstructor<TComponent extends Component = Component>
  extends ComponentConstructor<TComponent> {
  readonly componentName: string;
}

const defaultRegistry = new Map<string, ComponentConstructor>();

export class ComponentRegistry {
  private readonly components = new Map<string, ComponentConstructor>();

  constructor(private readonly parent: ComponentRegistry | null = null) {}

  /**
   * 使用组件类自身的静态 componentName 注册组件。
   */
  register(componentClass: NamedComponentConstructor): void;

  /**
   * 使用显式组件名称注册组件类。
   */
  register(name: string, componentClass: ComponentConstructor): void;
  register(nameOrClass: string | NamedComponentConstructor, componentClass?: ComponentConstructor): void {
    const registration = resolveComponentRegistration(nameOrClass, componentClass);
    this.components.set(registration.name, registration.componentClass);
  }

  /**
   * 按名称返回组件类，查找顺序为本地、父级、全局兜底注册表。
   */
  resolve(name: string): ComponentConstructor | null {
    return this.components.get(name) ?? this.parent?.resolve(name) ?? defaultRegistry.get(name) ?? null;
  }

  /**
   * 当前注册表或其父级可以解析名称时返回 true。
   */
  has(name: string): boolean {
    return this.resolve(name) !== null;
  }
}

/**
 * 在进程级兜底注册表中注册组件类。
 */
export function registerComponent(componentClass: NamedComponentConstructor): void;

/**
 * 使用显式名称在进程级兜底注册表中注册组件类。
 */
export function registerComponent(name: string, componentClass: ComponentConstructor): void;
export function registerComponent(
  nameOrClass: string | NamedComponentConstructor,
  componentClass?: ComponentConstructor
): void {
  const registration = resolveComponentRegistration(nameOrClass, componentClass);
  defaultRegistry.set(registration.name, registration.componentClass);
}

export const globalComponentRegistry = new ComponentRegistry();

function resolveComponentRegistration(
  nameOrClass: string | NamedComponentConstructor,
  componentClass?: ComponentConstructor
): { name: string; componentClass: ComponentConstructor } {
  if (typeof nameOrClass === "string") {
    if (!componentClass) throw new Error(`Component registration for "${nameOrClass}" requires a component class`);
    return { name: nameOrClass, componentClass };
  }

  return { name: nameOrClass.componentName, componentClass: nameOrClass };
}
