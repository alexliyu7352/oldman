import { Page, type PageConstructor } from "./page";
import { registerPage } from "./registry";

export type PageSetupContext = Pick<
  Page,
  | "root"
  | "state"
  | "signal"
  | "on"
  | "onCustom"
  | "listen"
  | "emit"
  | "onCoreEvent"
  | "runAction"
  | "loadStylesheet"
  | "loadScript"
  | "loadAssets"
  | "removeAsset"
  | "removeAssets"
  | "show"
  | "hide"
  | "toggle"
  | "withClasses"
  | "toggleClass"
  | "timers"
  | "events"
  | "assets"
  | "transitions"
  | "preferences"
  | "http"
  | "cleanup"
  | "$"
  | "$$"
  | "logger"
>;

export function page(name: string, setup: (context: PageSetupContext) => void | Promise<void>): void {
  class SetupPage extends Page {
    static pageName = name;

    async mount(): Promise<void> {
      const instance = this;
      await setup({
        root: this.root,
        get state() {
          return instance.state;
        },
        signal: this.signal,
        on: this.on.bind(this),
        onCustom: this.onCustom.bind(this),
        listen: this.listen.bind(this),
        emit: this.emit.bind(this),
        onCoreEvent: this.onCoreEvent.bind(this),
        runAction: this.runAction.bind(this),
        loadStylesheet: this.loadStylesheet.bind(this),
        loadScript: this.loadScript.bind(this),
        loadAssets: this.loadAssets.bind(this),
        removeAsset: this.removeAsset.bind(this),
        removeAssets: this.removeAssets.bind(this),
        show: this.show.bind(this),
        hide: this.hide.bind(this),
        toggle: this.toggle.bind(this),
        withClasses: this.withClasses.bind(this),
        toggleClass: this.toggleClass.bind(this),
        timers: this.timers,
        events: this.events,
        assets: this.assets,
        transitions: this.transitions,
        preferences: this.preferences,
        http: this.http,
        cleanup: this.cleanup.bind(this),
        $: this.$.bind(this),
        $$: this.$$.bind(this),
        logger: this.logger
      });
    }
  }

  registerPage(SetupPage);
}

/**
 * 使用后端渲染的 `data-om-page` 名称注册类风格页面。
 */
export function setupPage(name: string, pageClass: PageConstructor): void {
  registerPage(name, pageClass);
}
