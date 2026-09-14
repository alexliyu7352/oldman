import Swal from "sweetalert2";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Feedback } from "./feedback";

vi.mock("sweetalert2", () => ({
  default: {
    close: vi.fn(),
    fire: vi.fn(),
    isVisible: vi.fn()
  }
}));

const swalMock = vi.mocked(Swal);

class TestFeedback extends Feedback {
  /**
   * 注入测试默认配置，用于验证 customClass 深度合并。
   */
  protected override defaultOptions() {
    return {
      buttonsStyling: false,
      customClass: {
        cancelButton: "btn-danger",
        confirmButton: "btn-primary"
      }
    };
  }
}

describe("Feedback", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.clearAllMocks();
  });

  it("合并默认配置并调用 SweetAlert2", async () => {
    swalMock.fire.mockResolvedValue({ isConfirmed: true } as never);
    const root = document.createElement("div");
    const feedback = new TestFeedback(root);

    await feedback.fire({
      customClass: {
        confirmButton: "btn-success"
      },
      title: "保存成功"
    });

    expect(swalMock.fire).toHaveBeenCalledWith({
      buttonsStyling: false,
      customClass: {
        cancelButton: "btn-danger",
        confirmButton: "btn-success"
      },
      title: "保存成功"
    });
  });

  it("使用独立的 Toastify 叠放轻量提示", async () => {
    const feedback = new Feedback(document.createElement("div"));

    await feedback.toast({ icon: "success", text: "记录已经更新", title: "保存成功" });
    await feedback.toast({ titleText: "后台任务已启动" });

    const toasts = document.querySelectorAll(".toastify");
    const successToast = document.querySelector(".om-toast-success");
    expect(toasts).toHaveLength(2);
    expect(successToast?.textContent).toContain("保存成功");
    expect(successToast?.textContent).toContain("记录已经更新");
    expect(document.body.textContent).toContain("后台任务已启动");
    expect(swalMock.fire).not.toHaveBeenCalled();
  });

  it("把 confirm 结果转换为布尔值", async () => {
    swalMock.fire.mockResolvedValue({ isConfirmed: false } as never);
    const feedback = new Feedback(document.createElement("div"));

    await expect(feedback.confirm({ title: "确认删除?" })).resolves.toBe(false);
  });

  it("卸载时关闭仍在显示的反馈弹窗", async () => {
    const feedback = new Feedback(document.createElement("div"));
    await feedback.toast({ title: "稍后消失" });

    await feedback.unmount();

    expect(swalMock.close).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".toastify")?.classList.contains("on")).toBe(false);
    expect(feedback.isVisible()).toBe(false);
  });
});
