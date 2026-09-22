import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("oldman-admin frontend", () => {
  it("consumes dashboard framework through oldman-web public entries", () => {
    const source = readFileSync(resolve("src/main.ts"), "utf-8");
    const cssSource = readFileSync(resolve("src/admin.css"), "utf-8");

    expect(source).toContain('from "oldman-web/core"');
    expect(source).toContain('from "oldman-web/dashboard"');
    expect(source).toContain("createDashboardCrudComponentLoaders");
    expect(source).toContain('"table-filter-form"');
    expect(source).toContain('"date-time-picker"');
    expect(source).not.toContain('"form-modal"');
    expect(source).not.toContain('oldman-web/dashboard/form-modal');
    expect(source).toContain('modal: async () => (await import("oldman-web/dashboard/modal")).DashboardModal');
    expect(source).toContain('feedback: async () => (await import("oldman-web/dashboard/feedback")).DashboardFeedback');
    expect(source).toContain('form: async () => (await import("oldman-web/components/form")).Form');
    expect(source).toContain('"form-validator": async () => (await import("oldman-web/components/form-validator")).FormValidator');
    expect(source).not.toContain("class AdminFormModal");
    expect(source).not.toContain("handleSubmitResponse");
    expect(source).not.toContain("turboPrefetch");
    expect(source).toContain("dropdown:");
    expect(source).toContain('"./admin.css"');
    expect(cssSource).toContain('"oldman-web/styles/tailwind.css"');
    expect(cssSource).toContain('"oldman-web/styles/icons.css"');
    expect(cssSource).not.toContain(".oldman-sidebar {");
    expect(source).not.toContain("@app/");
    expect(source).not.toContain("/static/oldman-admin/");
    expect(source).toContain("readAdminBasePath()");
    expect(source).toContain("sidebarOptions: { defaultDashboardPath: adminBasePath }");
    expect(source).toContain("emptyNotificationTemplate: adminNotificationEmptyState");
    expect(source).toContain('class="empty-notification-elem om-empty om-empty-sm"');
    expect(source).not.toContain('defaultDashboardPath: "/admin"');
    expect(source).not.toContain("pageLoader: async () => undefined");
  });
});
