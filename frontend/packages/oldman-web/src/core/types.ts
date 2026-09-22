import type { Application } from "@hotwired/stimulus";
import type { HttpClient, HttpClientOptions } from "./http/client";
import type { StartActionsOptions } from "./actions/actions";
import type { StimulusControllerDefinitions } from "./stimulus/controllers";
import type { PageConstructor } from "./page/page";
import type { PageLoader } from "./page/registry";
import type { OldmanContext } from "./runtime/context";

export type StartOldmanActionsOptions = boolean | Omit<StartActionsOptions, "http" | "pageRegistry">;

export interface StartOldmanOptions {
  turbo?: boolean;
  actions?: StartOldmanActionsOptions;
  controllers?: StimulusControllerDefinitions;
  context?: OldmanContext;
  http?: HttpClientOptions;
  httpClient?: HttpClient;
  exposeGlobal?: string;
  pageLoader?: PageLoader;
  /** Page class used when `data-om-page` names nothing registered (after `pageLoader` had its chance). */
  fallbackPage?: PageConstructor;
}

export interface OldmanApp {
  started: boolean;
  readonly application: Application;
  readonly http: HttpClient;
  destroy(): Promise<void>;
}
