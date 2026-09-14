import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

type SourceAlias = {
  find: string | RegExp;
  replacement: string;
};

const frontendRoot = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(frontendRoot, "packages/oldman-web");
const sourceRoot = resolve(packageRoot, "src");

const sourceEntries: Readonly<Record<string, string>> = {
  "oldman-web": resolve(sourceRoot, "index.ts"),
  "oldman-web/core": resolve(sourceRoot, "core/index.ts"),
  "oldman-web/app": resolve(sourceRoot, "app/index.ts"),
  "oldman-web/dashboard": resolve(sourceRoot, "dashboard/index.ts"),
  "oldman-web/dashboard/feedback": resolve(sourceRoot, "dashboard/feedback.ts"),
  "oldman-web/dashboard/modal": resolve(sourceRoot, "dashboard/modal.ts"),
  "oldman-web/sse": resolve(sourceRoot, "sse/index.ts"),
  "oldman-web/components": resolve(sourceRoot, "components/index.ts"),
  "oldman-web/components/apex-chart": resolve(sourceRoot, "components/apex-chart.ts"),
  "oldman-web/components/alert": resolve(sourceRoot, "components/alert.ts"),
  "oldman-web/components/autocomplete": resolve(sourceRoot, "components/autocomplete.ts"),
  "oldman-web/components/back-to-top": resolve(sourceRoot, "components/back-to-top.ts"),
  "oldman-web/components/avatar": resolve(sourceRoot, "components/avatar.ts"),
  "oldman-web/components/carousel": resolve(sourceRoot, "components/carousel.ts"),
  "oldman-web/components/color-picker": resolve(sourceRoot, "components/color-picker.ts"),
  "oldman-web/components/countdown": resolve(sourceRoot, "components/countdown.ts"),
  "oldman-web/components/date-time-picker": resolve(sourceRoot, "components/date-time-picker.ts"),
  "oldman-web/components/dropdown": resolve(sourceRoot, "components/dropdown.ts"),
  "oldman-web/components/feedback": resolve(sourceRoot, "components/feedback.ts"),
  "oldman-web/components/form": resolve(sourceRoot, "components/form.ts"),
  "oldman-web/components/form-mask": resolve(sourceRoot, "components/form-mask.ts"),
  "oldman-web/components/form-repeater": resolve(sourceRoot, "components/form-repeater.ts"),
  "oldman-web/components/form-validator": resolve(sourceRoot, "components/form-validator.ts"),
  "oldman-web/components/gallery": resolve(sourceRoot, "components/gallery.ts"),
  "oldman-web/components/history-back": resolve(sourceRoot, "components/history-back.ts"),
  "oldman-web/components/input-spinner": resolve(sourceRoot, "components/input-spinner.ts"),
  "oldman-web/components/language-switcher": resolve(sourceRoot, "components/language-switcher.ts"),
  "oldman-web/components/list": resolve(sourceRoot, "components/list.ts"),
  "oldman-web/components/modal": resolve(sourceRoot, "components/modal.ts"),
  "oldman-web/components/multi-step-form": resolve(sourceRoot, "components/multi-step-form.ts"),
  "oldman-web/components/popover": resolve(sourceRoot, "components/popover.ts"),
  "oldman-web/components/preloader": resolve(sourceRoot, "components/preloader.ts"),
  "oldman-web/components/rich-text-editor": resolve(sourceRoot, "components/rich-text-editor.ts"),
  "oldman-web/components/scroll-area": resolve(sourceRoot, "components/scroll-area.ts"),
  "oldman-web/components/select": resolve(sourceRoot, "components/select.ts"),
  "oldman-web/components/sidebar-menu": resolve(sourceRoot, "components/sidebar-menu.ts"),
  "oldman-web/components/slider": resolve(sourceRoot, "components/slider.ts"),
  "oldman-web/components/slug-input": resolve(sourceRoot, "components/slug-input.ts"),
  "oldman-web/components/sortable-list": resolve(sourceRoot, "components/sortable-list.ts"),
  "oldman-web/components/table": resolve(sourceRoot, "components/table.ts"),
  "oldman-web/components/table-filter-form": resolve(sourceRoot, "components/table-filter-form.ts"),
  "oldman-web/components/tabs": resolve(sourceRoot, "components/tabs.ts"),
  "oldman-web/components/tags-input": resolve(sourceRoot, "components/tags-input.ts"),
  "oldman-web/components/tooltip": resolve(sourceRoot, "components/tooltip.ts"),
  "oldman-web/components/upload": resolve(sourceRoot, "components/upload.ts"),
  "oldman-web/styles/tailwind.css": resolve(sourceRoot, "styles/tailwind.css"),
  "oldman-web/styles/icons.css": resolve(sourceRoot, "styles/icons.css"),
  "oldman-web/package.json": resolve(packageRoot, "package.json")
};

/** Resolve the workspace package to source during local Vite development. */
export function oldmanWebAliases(): SourceAlias[] {
  return Object.entries(sourceEntries).map(([specifier, replacement]) => ({
    find: new RegExp(`^${escapeRegExp(specifier)}$`),
    replacement
  }));
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
