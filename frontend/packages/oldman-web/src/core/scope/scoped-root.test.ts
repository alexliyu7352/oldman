import { afterEach, describe, expect, it, vi } from "vitest";
import { Component } from "../component/component";
import { Page } from "../page/page";
import { createOldmanContext, resetOldmanContext, setOldmanContext } from "../runtime/context";
import { ScopedRoot } from "./scoped-root";

class ProbePage extends Page {
  static pageName = "scope-probe";
}

class ProbeComponent extends Component {
  static componentName = "scope-probe";
}

describe("ScopedRoot", () => {
  afterEach(() => {
    document.body.replaceChildren();
    resetOldmanContext();
  });

  function root(): HTMLElement {
    const element = document.createElement("main");
    document.body.append(element);
    return element;
  }

  it("is the one lifecycle both Page and Component run", () => {
    setOldmanContext(createOldmanContext({}));
    expect(new ProbePage(root())).toBeInstanceOf(ScopedRoot);
    expect(new ProbeComponent(root())).toBeInstanceOf(ScopedRoot);
  });

  it("aborts the scope as it enters unmounting, for both kinds", () => {
    // 卸载钩子因此看到的已经是 aborted 的信号：任何在那里发请求的使用方都得把取消
    // 当成正常退出。两个类曾各自实现这段，也就各自可能改掉它。
    setOldmanContext(createOldmanContext({}));
    for (const scope of [new ProbePage(root()), new ProbeComponent(root())]) {
      expect(scope.signal.aborted).toBe(false);
      scope.setState("unmounting");
      expect(scope.signal.aborted).toBe(true);
    }
  });

  it("keeps each kind's own state attribute and event shape", async () => {
    setOldmanContext(createOldmanContext({}));
    const cases = [
      { scope: new ProbePage(root()), event: "om:page:state", dataset: "omPageState", subject: "page" },
      { scope: new ProbeComponent(root()), event: "om:component:state", dataset: "omComponentState", subject: "component" }
    ];

    for (const { scope, event, dataset, subject } of cases) {
      const seen: Array<Record<string, unknown>> = [];
      scope.root.addEventListener(event, (received) => {
        seen.push((received as CustomEvent<Record<string, unknown>>).detail);
      });

      scope.setState("mounted");

      expect(scope.root.dataset[dataset]).toBe("mounted");
      expect(seen).toHaveLength(1);
      expect(seen[0]![subject]).toBe(scope);
      expect(seen[0]!.previousState).toBe("created");
      expect(seen[0]!.state).toBe("mounted");
    }
  });

  it("ignores a state that is already current", () => {
    setOldmanContext(createOldmanContext({}));
    const scope = new ProbeComponent(root());
    let events = 0;
    scope.root.addEventListener("om:component:state", () => {
      events += 1;
    });

    scope.setState("mounted");
    scope.setState("mounted");
    expect(events).toBe(1);
  });

  it("withClasses removes its classes itself, and registers nothing to repeat it", async () => {
    // 旧代码每调用一次 withClasses 就往清理注册表压一个"移除这些 class"的闭包,
    // 而 TransitionService.withClasses 的 finally 已经保证了移除(异常路径也走)。
    // 闭包还持有 element,所以节点早已离开文档也回收不掉,直到整个作用域卸载。
    setOldmanContext(createOldmanContext({}));
    const page = new ProbePage(root());
    const element = document.createElement("div");
    document.body.append(element);
    const remove = vi.spyOn(element.classList, "remove");

    await expect(page.withClasses(element, ["busy"], () => {
      expect(element.classList.contains("busy")).toBe(true);
      throw new Error("callback failed");
    })).rejects.toThrow("callback failed");

    // 异常路径上类名也已经移除——这正是那条注册多余的原因。
    expect(element.classList.contains("busy")).toBe(false);
    expect(remove).toHaveBeenCalledTimes(1);

    await page.runCleanup();
    // 卸载时不再重复做一遍 transitions 已经做过的事。
    expect(remove).toHaveBeenCalledTimes(1);
  });
});
