import Swal from "sweetalert2";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Modal } from "../components/modal";
import { DashboardFeedback } from "./feedback";
import { DashboardModal } from "./modal";

vi.mock("sweetalert2", () => ({
  default: {
    close: vi.fn(),
    fire: vi.fn(),
    isVisible: vi.fn()
  }
}));

const swalMock = vi.mocked(Swal);

describe("Dashboard theme adapters", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("applies the shared Dashboard visual contract to Modal", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <button type="button" data-om-modal-target="#shared-modal">Open</button>
      <div id="shared-modal" class="om-modal" hidden aria-hidden="true" style="display: none;">
        <div class="om-modal-dialog">
          <div class="om-modal-surface">
            <div class="om-modal-body"><button type="button" data-om-modal-close>Close</button></div>
          </div>
        </div>
      </div>
    `;
    const root = document.querySelector<HTMLElement>("#shared-modal")!;
    const modal = new DashboardModal(root);

    await modal.start();
    document.querySelector<HTMLButtonElement>("[data-om-modal-target]")!.click();
    await vi.waitFor(() => expect(root.hidden).toBe(false));

    expect(root.classList.contains("is-open")).toBe(true);
    expect(root.style.display).toBe("block");
    expect(root.dataset.omModalManaged).toBe("true");
    expect(document.body.classList.contains("om-modal-open")).toBe(true);
    const backdrop = document.querySelector(".om-modal-backdrop[data-om-modal-backdrop='true']");
    expect(backdrop).not.toBeNull();
    expect(backdrop?.classList.contains("is-open")).toBe(true);
    expect(root.querySelector(".om-modal-surface")?.getAttribute("tabindex")).toBe("-1");

    document.querySelector<HTMLButtonElement>("[data-om-modal-close]")!.click();
    expect(root.dataset.omState).toBe("closing");
    expect(root.hidden).toBe(false);
    expect(backdrop?.classList.contains("is-open")).toBe(false);
    vi.advanceTimersByTime(250);
    await Promise.resolve();

    expect(root.hidden).toBe(true);
    expect(root.style.display).toBe("none");
    expect(document.body.classList.contains("om-modal-open")).toBe(false);
    expect(document.querySelector("[data-om-modal-backdrop='true']")).toBeNull();
    await modal.stop();
  });

  it("honors the shared static-backdrop and keyboard flags", async () => {
    document.body.innerHTML = `
      <button type="button" data-om-modal-target="#static-modal">Open</button>
      <div id="static-modal" class="om-modal" data-om-backdrop="static" data-om-keyboard="false" style="display: none;">
        <div class="om-modal-dialog"><div class="om-modal-surface"><div class="om-modal-body">Body</div></div></div>
      </div>
    `;
    const root = document.querySelector<HTMLElement>("#static-modal")!;
    const modal = new DashboardModal(root);

    await modal.start();
    document.querySelector<HTMLButtonElement>("[data-om-modal-target]")!.click();
    await vi.waitFor(() => expect(root.hidden).toBe(false));
    root.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    document.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Escape" }));

    expect(root.hidden).toBe(false);
    expect(root.dataset.omState).toBe("open");
    modal.close("programmatic");
    await modal.stop();
  });

  it("keeps Dashboard surface/content ownership in the Modal adapter", async () => {
    document.body.innerHTML = `
      <section id="headless-modal" role="dialog" hidden>
        <div class="om-modal-surface"><div class="om-modal-body">Headless initial</div></div>
      </section>
      <section id="dashboard-modal" class="om-modal" hidden>
        <div class="om-modal-dialog">
          <div class="om-modal-surface"><div class="om-modal-body">Dashboard initial</div></div>
        </div>
      </section>
    `;
    const headlessRoot = document.querySelector<HTMLElement>("#headless-modal")!;
    const dashboardRoot = document.querySelector<HTMLElement>("#dashboard-modal")!;
    const headless = new Modal(headlessRoot);
    const dashboard = new DashboardModal(dashboardRoot);

    await headless.start();
    await dashboard.start();
    headless.setParts({ html: "Headless replacement" });
    dashboard.setParts({ html: "Dashboard replacement" });

    expect(headlessRoot.innerHTML).toBe("Headless replacement");
    expect(headlessRoot.querySelector(".om-modal-surface")).toBeNull();
    expect(dashboardRoot.querySelector(".om-modal-surface")).not.toBeNull();
    expect(dashboardRoot.querySelector<HTMLElement>(".om-modal-body")?.innerHTML).toBe("Dashboard replacement");

    await dashboard.stop();
    await headless.stop();
  });

  it("applies the same SweetAlert button classes for every Dashboard consumer", async () => {
    swalMock.fire.mockResolvedValue({ isConfirmed: true } as never);
    const feedback = new DashboardFeedback(document.createElement("div"));

    await feedback.alert({ title: "提示" });

    expect(swalMock.fire).toHaveBeenCalledWith(
      expect.objectContaining({
        buttonsStyling: false,
        customClass: {
          actions: "gap-2",
          cancelButton: "om-button om-button-danger mt-2",
          confirmButton: "om-button om-button-primary mt-2",
          denyButton: "om-button om-button-soft-info mt-2"
        },
        showCloseButton: true,
        title: "提示"
      })
    );
  });

});
