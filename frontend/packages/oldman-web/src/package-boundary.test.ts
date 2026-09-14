import { describe, expect, expectTypeOf, it } from "vitest";
import {
  ComponentRegistry,
  EventStreamClient,
  OLDMAN_WEB_VERSION,
  SESSION_INVALIDATED_EVENT
} from "./index";
import type { SessionInvalidatedPayload } from "./index";
import { EventStreamClient as SubpathEventStreamClient } from "./sse/index";
import {
  DashboardFeedback,
  DashboardModal,
  DashboardPage,
  createDashboardComponentLoaders,
  createDashboardCrudComponentLoaders
} from "./dashboard/index";
import { Table, TagsInput } from "./components/index";
import type { ModalDynamicContentMountDetail } from "./components/index";
import { oldmanComponentNames } from "./components/loaders";

describe("oldman-web package boundary", () => {
  it("keeps the root entry light and usable", () => {
    expect(OLDMAN_WEB_VERSION).toMatch(/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/);
    expect(new ComponentRegistry()).toBeInstanceOf(ComponentRegistry);
  });

  it("exports the same SSE client from the root and dedicated subpath", () => {
    expect(EventStreamClient).toBe(SubpathEventStreamClient);
    expect(SESSION_INVALIDATED_EVENT).toBe("oldman.session.invalidated");
    expectTypeOf<SessionInvalidatedPayload>().toMatchTypeOf<{
      login_url: string;
      message: string;
      title: string;
    }>();
  });

  it("exposes dashboard shell types and shared theme component defaults", async () => {
    const page = new DashboardPage({ root: document.body });
    const loaders = createDashboardComponentLoaders();

    expect(page).toBeInstanceOf(DashboardPage);
    expect(loaders).toHaveProperty("table");
    expect(loaders).toHaveProperty("apex-chart");
    expect(await loaders.feedback?.()).toBe(DashboardFeedback);
    expect(await loaders.modal?.()).toBe(DashboardModal);
    expect(DashboardFeedback.name).toBe("DashboardFeedback");
    expect(DashboardModal.name).toBe("DashboardModal");
  });

  it("declares all framework component subpaths required by the audit", () => {
    expect(oldmanComponentNames).toContain("apex-chart");
    expect(oldmanComponentNames).toContain("alert");
    expect(oldmanComponentNames).toContain("avatar");
    expect(oldmanComponentNames).toContain("carousel");
    expect(oldmanComponentNames).toContain("color-picker");
    expect(oldmanComponentNames).toContain("countdown");
    expect(oldmanComponentNames).toContain("gallery");
    expect(oldmanComponentNames).toContain("input-spinner");
    expect(oldmanComponentNames).toContain("slug-input");
    expect(oldmanComponentNames).toContain("tags-input");
    expect(oldmanComponentNames).toContain("multi-step-form");
    expect(oldmanComponentNames).toContain("tabs");
    expect(oldmanComponentNames).toContain("tooltip");
    expect(oldmanComponentNames).toContain("popover");
    expect(oldmanComponentNames).toContain("rich-text-editor");
    expect(oldmanComponentNames).toContain("table");
    expect(oldmanComponentNames).toContain("history-back");
    expect(Table.componentName).toBe("table");
    expect(TagsInput.componentName).toBe("tags-input");
    expectTypeOf<ModalDynamicContentMountDetail>().toHaveProperty("waitUntil");
  });

  it("keeps the CRUD loader set light and accepts shared theme adapter overrides", async () => {
    const loaders = createDashboardCrudComponentLoaders({
      feedback: async () => DashboardFeedback
    });

    expect(Object.keys(loaders).sort()).toEqual(["feedback", "sidebar-menu", "table"]);
    expect(await loaders.feedback?.()).toBe(DashboardFeedback);
    expect(loaders).not.toHaveProperty("apex-chart");
    expect(loaders).not.toHaveProperty("date-time-picker");
    expect(loaders).not.toHaveProperty("select");
  });
});
