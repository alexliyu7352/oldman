import type { Application, ControllerConstructor } from "@hotwired/stimulus";

export type StimulusControllerDefinitions = Record<string, ControllerConstructor>;

let currentApplication: Application | null = null;
const pendingControllers: StimulusControllerDefinitions = {};

export function setStimulusApplication(application: Application | null): void {
  if (!application) {
    currentApplication = null;
    return;
  }

  const previousApplication = currentApplication;
  try {
    registerControllers(pendingControllers, application);
  } catch (error) {
    currentApplication = previousApplication;
    clearPendingControllers();
    throw error;
  }

  currentApplication = application;
  clearPendingControllers();
}

export function getStimulusApplication(): Application | null {
  return currentApplication;
}

export function registerController(
  identifier: string,
  controller: ControllerConstructor,
  application: Application | null = currentApplication
): Application | null {
  if (!application) {
    pendingControllers[identifier] = controller;
    return null;
  }

  application.register(identifier, controller);
  return application;
}

export function registerControllers(
  controllers: StimulusControllerDefinitions,
  application: Application | null = currentApplication
): Application | null {
  if (!application) {
    Object.assign(pendingControllers, controllers);
    return null;
  }

  for (const [identifier, controller] of Object.entries(controllers)) {
    application.register(identifier, controller);
  }

  return application;
}

export function clearPendingControllers(): void {
  for (const identifier of Object.keys(pendingControllers)) {
    delete pendingControllers[identifier];
  }
}
