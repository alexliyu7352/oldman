import { afterEach, describe, expect, it } from "vitest";
import { DashboardTopbar, type DashboardTopbarNotificationDetail } from "./topbar";

class TestDashboardTopbar extends DashboardTopbar {
  renderNotification(detail: DashboardTopbarNotificationDetail): string {
    return this.notificationTemplate(detail);
  }
}

describe("DashboardTopbar", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("uses a neutral notification route unless a consumer configures one", () => {
    const neutral = new TestDashboardTopbar(document.body);
    const configured = new TestDashboardTopbar(document.body, { defaultNotificationHref: "/control" });

    expect(neutral.renderNotification({ title: "Notice" })).toContain('href="/"');
    expect(configured.renderNotification({ title: "Notice" })).toContain('href="/control"');
    expect(configured.renderNotification({ href: "/explicit", title: "Notice" })).toContain('href="/explicit"');
  });

  it("keeps runtime activity separate from persistent user notifications", async () => {
    document.body.innerHTML = `
      <span data-om-user-notification-count>8</span>
      <section data-om-user-notification-topbar>
        <div data-om-user-notification-slot>
          <a data-om-user-notification-preview data-om-user-notification-id="91">Persistent</a>
        </div>
      </section>
      <section data-om-activity-notifications>
        <div data-om-activity-notification-list>
          <div data-om-activity-notification-empty>Empty</div>
        </div>
        <span data-om-activity-notification-count>0</span>
        <div data-om-activity-notification-actions hidden>
          <span data-om-activity-notification-selection-count>0</span>
          <button data-om-activity-notification-delete-selected>Delete</button>
        </div>
      </section>
    `;
    const topbar = new DashboardTopbar(document.body);
    await topbar.start();

    document.dispatchEvent(new CustomEvent("om:notification:add", {
      detail: {
        description: '<img src=x onerror="bad">',
        href: '/safe?value="quoted"',
        icon: "ri-alert-line bad<script>",
        title: "<b>Activity</b>"
      }
    }));

    const activityItem = document.querySelector<HTMLElement>("[data-om-activity-notification-item]")!;
    expect(activityItem).not.toBeNull();
    expect(activityItem.textContent).toContain("<b>Activity</b>");
    expect(activityItem.querySelector("script, img")).toBeNull();
    expect(activityItem.querySelector("i")?.className).toBe("ri-alert-line");
    expect(document.querySelector("[data-om-user-notification-preview]")?.textContent).toBe("Persistent");
    expect(document.querySelector("[data-om-user-notification-count]")?.textContent).toBe("8");
    expect(document.querySelector("[data-om-activity-notification-count]")?.textContent).toBe("1");

    const checkbox = activityItem.querySelector<HTMLInputElement>("[data-om-activity-notification-select]")!;
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    expect(document.querySelector("[data-om-activity-notification-selection-count]")?.textContent).toBe("1");
    document.querySelector<HTMLElement>("[data-om-activity-notification-delete-selected]")!.click();
    expect(document.querySelector("[data-om-activity-notification-item]")).toBeNull();
    expect(document.querySelector("[data-om-user-notification-preview]")).not.toBeNull();
    expect(document.querySelector("[data-om-user-notification-count]")?.textContent).toBe("8");

    await topbar.stop();
  });
});
