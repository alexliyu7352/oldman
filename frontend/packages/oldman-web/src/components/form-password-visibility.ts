import { Component } from "../core/component/component";

const PASSWORD_TOGGLE_SELECTOR = "[data-om-password-toggle]";

/**
 * 在组件范围内挂载 renderer 生成的密码可见性协议。
 */
export function bindPasswordVisibility(component: Component): void {
  for (const button of component.root.querySelectorAll(PASSWORD_TOGGLE_SELECTOR)) {
    if (!(button instanceof HTMLButtonElement)) continue;
    syncPasswordVisibility(component.root, button);
  }

  component.on("click", PASSWORD_TOGGLE_SELECTOR, (event, button) => {
    // 嵌套 Form 时由离按钮最近的组件处理，避免冒泡后再次切换。
    if (event.defaultPrevented) return;
    if (!(button instanceof HTMLButtonElement)) return;
    const input = resolvePasswordInput(component.root, button);
    if (!input) return;

    event.preventDefault();
    input.type = input.type === "password" ? "text" : "password";
    syncPasswordVisibility(component.root, button);
  });
}

function resolvePasswordInput(root: HTMLElement, button: HTMLButtonElement): HTMLInputElement | null {
  if (!root.contains(button)) return null;

  const form = button.closest("form");
  if (!(form instanceof HTMLFormElement) || !root.contains(form)) return null;

  const inputId = button.getAttribute("aria-controls")?.trim();
  if (!inputId) return null;

  const matches = Array.from(form.querySelectorAll<HTMLElement>("[id]")).filter((candidate) => candidate.id === inputId);
  if (matches.length !== 1) return null;

  const input = matches[0];
  if (!(input instanceof HTMLInputElement) || input.closest("form") !== form) return null;
  if (input.type !== "password" && input.type !== "text") return null;
  return input;
}

function syncPasswordVisibility(root: HTMLElement, button: HTMLButtonElement): void {
  const input = resolvePasswordInput(root, button);
  if (!input) return;

  const showLabel = button.getAttribute("data-om-label-show")?.trim();
  const hideLabel = button.getAttribute("data-om-label-hide")?.trim();
  if (!showLabel || !hideLabel) return;

  const visible = input.type === "text";
  button.setAttribute("aria-pressed", visible ? "true" : "false");
  button.setAttribute("aria-label", visible ? hideLabel : showLabel);
  button.setAttribute("data-om-password-visible", visible ? "true" : "false");
  // The icon shows the action's result: an open eye while hidden, a crossed eye while visible.
  const icon = button.querySelector<HTMLElement>("i");
  if (icon) icon.className = visible ? "ri-eye-off-line" : "ri-eye-line";
}
