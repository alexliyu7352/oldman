import type { ComponentConstructor } from "../core/index";

export const oldmanComponentNames = [
  "apex-chart",
  "alert",
  "autocomplete",
  "avatar",
  "back-to-top",
  "carousel",
  "color-picker",
  "countdown",
  "date-time-picker",
  "dropdown",
  "feedback",
  "form",
  "form-mask",
  "form-repeater",
  "form-validator",
  "gallery",
  "history-back",
  "input-spinner",
  "language-switcher",
  "list",
  "modal",
  "multi-step-form",
  "popover",
  "preloader",
  "rich-text-editor",
  "scroll-area",
  "select",
  "sidebar-menu",
  "slider",
  "slug-input",
  "tags-input",
  "sortable-list",
  "table",
  "table-filter-form",
  "tabs",
  "tooltip",
  "upload"
] as const;

export type OldmanFrameworkComponentName = (typeof oldmanComponentNames)[number];

export type OldmanComponentLoader = () => Promise<ComponentConstructor>;

export const loadSidebarMenuComponent: OldmanComponentLoader = async () => (await import("./sidebar-menu")).SidebarMenu;
export const loadTableComponent: OldmanComponentLoader = async () => (await import("./table")).Table;

export function createFrameworkComponentLoaders(): Record<OldmanFrameworkComponentName, OldmanComponentLoader> {
  return {
    "apex-chart": async () => (await import("./apex-chart")).ApexChart,
    alert: async () => (await import("./alert")).Alert,
    autocomplete: async () => (await import("./autocomplete")).Autocomplete,
    avatar: async () => (await import("./avatar")).Avatar,
    "back-to-top": async () => (await import("./back-to-top")).BackToTop,
    carousel: async () => (await import("./carousel")).Carousel,
    "color-picker": async () => (await import("./color-picker")).ColorPicker,
    countdown: async () => (await import("./countdown")).Countdown,
    "date-time-picker": async () => (await import("./date-time-picker")).DateTimePicker,
    dropdown: async () => (await import("./dropdown")).Dropdown,
    feedback: async () => (await import("./feedback")).Feedback,
    form: async () => (await import("./form")).Form,
    "form-mask": async () => (await import("./form-mask")).FormMask,
    "form-repeater": async () => (await import("./form-repeater")).FormRepeater,
    "form-validator": async () => (await import("./form-validator")).FormValidator,
    gallery: async () => (await import("./gallery")).Gallery,
    "history-back": async () => (await import("./history-back")).HistoryBack,
    "input-spinner": async () => (await import("./input-spinner")).InputSpinner,
    "language-switcher": async () => (await import("./language-switcher")).LanguageSwitcher,
    list: async () => (await import("./list")).List,
    modal: async () => (await import("./modal")).Modal,
    "multi-step-form": async () => (await import("./multi-step-form")).MultiStepForm,
    popover: async () => (await import("./popover")).Popover,
    preloader: async () => (await import("./preloader")).Preloader,
    "rich-text-editor": async () => (await import("./rich-text-editor")).RichTextEditor,
    "scroll-area": async () => (await import("./scroll-area")).ScrollArea,
    select: async () => (await import("./select")).Select,
    "sidebar-menu": loadSidebarMenuComponent,
    slider: async () => (await import("./slider")).Slider,
    "slug-input": async () => (await import("./slug-input")).SlugInput,
    "tags-input": async () => (await import("./tags-input")).TagsInput,
    "sortable-list": async () => (await import("./sortable-list")).SortableList,
    table: loadTableComponent,
    "table-filter-form": async () => (await import("./table-filter-form")).TableFilterForm,
    tabs: async () => (await import("./tabs")).Tabs,
    tooltip: async () => (await import("./tooltip")).Tooltip,
    upload: async () => (await import("./upload")).Upload
  };
}
