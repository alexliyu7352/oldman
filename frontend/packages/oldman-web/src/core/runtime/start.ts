import { Application } from "@hotwired/stimulus";
import { startActions } from "../actions/actions";
import { PageRegistry } from "../page/registry";
import { startPageLifecycle } from "../page/lifecycle";
import { createOldmanContext, resetOldmanContext, setOldmanContext } from "./context";
import { registerControllers, setStimulusApplication } from "../stimulus/controllers";
import type { OldmanApp, StartOldmanActionsOptions, StartOldmanOptions } from "../types";
import type { StartActionsOptions } from "../actions/actions";

export async function startOldman(options: StartOldmanOptions = {}): Promise<OldmanApp> {
  if (options.turbo ?? true) {
    const Turbo = await import("@hotwired/turbo");
    Turbo.start();
    Turbo.session.linkPrefetchObserver.stop();
  }

  const context =
    options.context ??
    createOldmanContext({
      document,
      ...(options.httpClient ? { http: options.httpClient } : {}),
      ...(options.http ? { httpOptions: options.http } : {}),
      pageRegistry: new PageRegistry()
    });
  const http = context.http;
  setOldmanContext(context);
  const cleanupCallbacks: Array<() => void | Promise<void>> = [];
  let application: Application | undefined;
  let destroyPromise: Promise<void> | undefined;

  const actionOptions = normalizeActionsOptions(options.actions);
  try {
    application = Application.start();
    setStimulusApplication(application);
    registerControllers(options.controllers ?? {}, application);

    if (actionOptions) {
      cleanupCallbacks.push(startActions({ ...actionOptions, http, pageRegistry: context.pageRegistry }));
    }

    const lifecycleOptions = options.pageLoader ? { loadPage: options.pageLoader } : {};
    cleanupCallbacks.push(await startPageLifecycle({ ...lifecycleOptions, registry: context.pageRegistry }));

    const startedApplication = application;
    const app: OldmanApp = {
      started: true,
      application: startedApplication,
      http,
      async destroy() {
        destroyPromise ??= (async () => {
          try {
            await cleanupStartedRuntime(startedApplication, cleanupCallbacks);
          } finally {
            app.started = false;
            resetOldmanContext();
          }
        })();

        await destroyPromise;
      }
    };

    if (options.exposeGlobal) {
      Object.assign(window, { [options.exposeGlobal]: app });
    }

    return app;
  } catch (error) {
    if (application) {
      try {
        await cleanupStartedRuntime(application, cleanupCallbacks);
      } catch {
        // 清理失败不应覆盖原始启动错误。
      }
    }
    resetOldmanContext();
    throw error;
  }
}

function normalizeActionsOptions(
  actions: StartOldmanActionsOptions | undefined
): Omit<StartActionsOptions, "http" | "pageRegistry"> | null {
  if (actions === false) return null;
  if (actions === true || actions === undefined) return {};
  return actions;
}

async function cleanupStartedRuntime(
  application: Application,
  cleanupCallbacks: Array<() => void | Promise<void>>
): Promise<void> {
  const cleanupErrors: unknown[] = [];

  for (const callback of [...cleanupCallbacks].reverse()) {
    try {
      await callback();
    } catch (error) {
      cleanupErrors.push(error);
    }
  }

  try {
    application.stop();
  } catch (error) {
    cleanupErrors.push(error);
  } finally {
    setStimulusApplication(null);
  }

  if (cleanupErrors.length === 1) {
    throw cleanupErrors[0];
  }

  if (cleanupErrors.length > 1) {
    throw new AggregateError(cleanupErrors, "Runtime cleanup failed");
  }
}
