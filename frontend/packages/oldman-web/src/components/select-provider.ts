/**
 * Select 和 Autocomplete 共用的远程 provider 协议工具。
 *
 * 这两个组件走同一套后端协议，`autocomplete.ts` 本来就从 `select.ts` import
 * `normalizeSelectOptions`。解析共用了，判定和合并却各抄了一份，而且**已经分叉**：
 * select 的 `deduplicateOptions` 合并时保留 `selected`（分页追加不能丢掉已选中项），
 * autocomplete 的那份先到先得、后来的整条丢弃。这里收敛到前者。
 *
 * 只收敛纯函数。两个组件的请求管线**没有**合并：Select 挂在 Choices 的下拉里、用
 * `listen(button)` 绑分页按钮；Autocomplete 自己渲染列表、用事件委托。强行统一
 * 只会造出一个带两套分支的抽象。
 */

import { cssEscape } from "../core/dom/helpers";
import type { I18nRuntime } from "../core/i18n";
import type { SelectOption } from "./select";

/** 连续输入合并成一次远程查询的延迟。 */
export const REMOTE_SEARCH_DELAY_MS = 150;

/** 判断响应是否符合后端 provider 的分页协议。 */
export function isProviderResponse(input: unknown): input is { more: boolean; results: unknown[] } {
  if (typeof input !== "object" || input === null) return false;
  const candidate = input as { more?: unknown; results?: unknown };
  return Array.isArray(candidate.results) && typeof candidate.more === "boolean";
}

/**
 * 把异常转成可展示的消息。
 *
 * 走 i18n：组件其余十几条文案都走了，只有出错时会蹦出一句英文。沿用 `table.ts` 已经
 * 在用的 "Request failed"，不为同一件事再引入一个新 msgid。
 */
export function providerErrorMessage(error: unknown, i18n: I18nRuntime): string {
  return error instanceof Error ? error.message : i18n.t("Request failed");
}

/**
 * 按 value 合并分页结果，保留任一侧的 `selected`。
 *
 * 保留 selected 是必须的：编辑表单里已选中的值可能出现在第二页，合并时丢掉它，
 * 用户翻一次页就看到选择被清空了。
 */
export function deduplicateOptions(options: SelectOption[]): SelectOption[] {
  const unique = new Map<string, SelectOption>();
  for (const option of options) {
    const current = unique.get(option.value);
    unique.set(option.value, current ? { ...current, selected: Boolean(current.selected || option.selected) } : option);
  }
  return [...unique.values()];
}

/** 读取白名单依赖字段的当前值，空值不提交。 */
export function dependentValues(root: HTMLElement, fields: string | null): Array<[string, string]> {
  if (!fields) return [];
  const container = root.closest("form") ?? root;
  return fields
    .split(",")
    .map((field) => field.trim())
    .filter(Boolean)
    .flatMap((field): Array<[string, string]> => {
      const control = container.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
        `[name="${cssEscape(field)}"]`
      );
      if (!control) return [];
      const value = control instanceof HTMLSelectElement && control.multiple
        ? Array.from(control.selectedOptions).map((option) => option.value).filter(Boolean).join(",")
        : control.value;
      return value === "" ? [] : [[field, value]];
    });
}
