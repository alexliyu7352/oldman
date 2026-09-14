import Pickr from "@simonwep/pickr";
import "@simonwep/pickr/dist/themes/nano.min.css";
import "./color-picker.scss";
import { Component } from "../core/component/component";

type PickrInstance = ReturnType<typeof Pickr.create>;

/** 用 Pickr 增强原生颜色输入，并让隐藏字段提交完整 HEXA 值。 */
export class ColorPicker extends Component {
  static readonly componentName = "color-picker";
  private initialValue = "";
  private instance: PickrInstance | null = null;
  private native: HTMLInputElement | null = null;
  private trigger: HTMLElement | null = null;
  private value: HTMLInputElement | null = null;

  override async mount(): Promise<void> {
    const native = this.root.querySelector<HTMLInputElement>("[data-om-color-picker-native]");
    const value = this.root.querySelector<HTMLInputElement>("[data-om-color-picker-value]");
    const trigger = this.root.querySelector<HTMLElement>("[data-om-color-picker-trigger]");
    if (!native || !value || !trigger) throw new Error("ColorPicker requires native, value and trigger controls");

    this.native = native;
    this.value = value;
    this.trigger = trigger;
    const name = native.name;
    native.removeAttribute("name");
    native.hidden = true;
    value.name = name;
    value.disabled = native.disabled;
    trigger.hidden = false;

    const allowAlpha = this.root.dataset.omColorPickerAlpha === "true";
    const initial = value.value || native.value;
    this.initialValue = initial;
    this.instance = Pickr.create({
      el: trigger,
      useAsButton: true,
      theme: "nano",
      default: initial,
      defaultRepresentation: "HEXA",
      disabled: native.disabled,
      lockOpacity: !allowAlpha,
      closeOnScroll: true,
      components: {
        palette: true,
        preview: true,
        opacity: allowAlpha,
        hue: true,
        interaction: { hex: true, input: true, cancel: true, save: true }
      },
      i18n: {
        "btn:toggle": this.i18n.t("Choose color"),
        "btn:save": this.i18n.t("Save"),
        "btn:cancel": this.i18n.t("Cancel")
      }
    });
    this.instance.on("change", (color: Pickr.HSVaColor) => this.syncValue(color, value, native, allowAlpha));
    this.instance.on("cancel", () => {
      const color = this.instance?.getColor();
      if (color) this.syncValue(color, value, native, allowAlpha);
    });
    this.instance.on("save", (color: Pickr.HSVaColor) => {
      this.syncValue(color, value, native, allowAlpha, true);
      this.instance?.hide();
    });
    this.listen(native.form ?? this.root, "reset", () => {
      queueMicrotask(() => {
        const resetValue = this.initialValue;
        value.value = resetValue;
        this.instance?.setColor(resetValue, true);
        native.value = resetValue.slice(0, 7);
      });
    });
  }

  override async unmount(): Promise<void> {
    this.instance?.destroyAndRemove();
    if (this.native && this.value) {
      this.native.name = this.value.name;
      this.native.hidden = false;
      this.value.removeAttribute("name");
      this.value.disabled = true;
    }
    if (this.trigger) this.trigger.hidden = true;
    this.instance = null;
    this.native = null;
    this.trigger = null;
    this.value = null;
  }

  private syncValue(
    color: Pickr.HSVaColor,
    value: HTMLInputElement,
    native: HTMLInputElement,
    allowAlpha: boolean,
    committed = false
  ): void {
    const hex = color.toHEXA().toString().toLowerCase();
    value.value = allowAlpha ? hex : hex.slice(0, 7);
    native.value = hex.slice(0, 7);
    value.dispatchEvent(new Event(committed ? "change" : "input", { bubbles: true }));
  }
}
