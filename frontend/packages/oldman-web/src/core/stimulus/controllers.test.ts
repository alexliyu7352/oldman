import { Application, Controller } from "@hotwired/stimulus";
import { afterEach, describe, expect, it } from "vitest";
import {
  clearPendingControllers,
  getStimulusApplication,
  registerController,
  registerControllers,
  setStimulusApplication
} from "./controllers";

class TestController extends Controller {}
class OtherController extends Controller {}

describe("stimulus controller helpers", () => {
  afterEach(() => {
    setStimulusApplication(null);
    clearPendingControllers();
  });

  it("queues controllers registered before an active application exists", () => {
    expect(registerController("test", TestController)).toBeNull();

    const application = Application.start();
    try {
      setStimulusApplication(application);

      const router = application.router as unknown as { modulesByIdentifier: Map<string, unknown> };
      expect(router.modulesByIdentifier.has("test")).toBe(true);
    } finally {
      application.stop();
    }
  });

  it("clears queued controllers after registering them on an application", () => {
    registerController("test", TestController);

    const firstApplication = Application.start();
    try {
      setStimulusApplication(firstApplication);
    } finally {
      firstApplication.stop();
      setStimulusApplication(null);
    }

    const secondApplication = Application.start();
    try {
      setStimulusApplication(secondApplication);
      registerController("other", OtherController);

      const router = secondApplication.router as unknown as { modulesByIdentifier: Map<string, unknown> };
      expect(router.modulesByIdentifier.has("test")).toBe(false);
      expect(router.modulesByIdentifier.has("other")).toBe(true);
    } finally {
      secondApplication.stop();
    }
  });

  it("registers controllers on the provided application", () => {
    const application = Application.start();
    try {
      registerControllers({ test: TestController }, application);

      const router = application.router as unknown as { modulesByIdentifier: Map<string, unknown> };
      expect(router.modulesByIdentifier.has("test")).toBe(true);
    } finally {
      application.stop();
    }
  });

  it("stores the current application", () => {
    const application = Application.start();
    try {
      setStimulusApplication(application);

      expect(getStimulusApplication()).toBe(application);
    } finally {
      application.stop();
    }
  });
});
