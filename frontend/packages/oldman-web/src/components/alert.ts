import { Component } from "../core/component/component";
import { setHidden } from "../core/dom/helpers";

export interface AlertDismissDetail {
  component: Alert;
}

/** 处理可关闭 Alert 的最小声明式行为。 */
export class Alert extends Component {
  static readonly componentName = "alert";

  /** 关闭当前 Alert，并通知页面级消费者。 */
  override async mount(): Promise<void> {
    this.on("click", "[data-om-alert-dismiss]", (event) => {
      event.preventDefault();
      setHidden(this.root, true);
      this.emit<AlertDismissDetail>("om:alert:dismiss", { component: this });
    });
  }
}
