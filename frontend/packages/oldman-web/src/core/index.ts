export const OLDMAN_WEB_VERSION = "0.2.0";

export { startOldman } from "./runtime/start";
export type { OldmanApp, StartOldmanActionsOptions, StartOldmanOptions } from "./types";
export { createOldmanContext, getOldmanContext, resetOldmanContext, setOldmanContext } from "./runtime/context";
export type { CreateOldmanContextOptions, OldmanContext } from "./runtime/context";
export { onCoreEvent } from "./events";
export type { CoreEvent, CoreEventHandler, CoreEventMap, CoreEventName, StopCoreEventListener } from "./events";
export { abortable, abortError, isCanceledError } from "./services/abort";
export { CleanupRegistry } from "./services/cleanup";
export { EventService } from "./services/events";
export type { CustomEventTarget, DirectEventHandler, EmitEventOptions } from "./services/events";
export { TimerService } from "./services/timers";
export { ScopedPreloader } from "./services/preloader";
export type { ScopedPreloaderEventDetail, ScopedPreloaderOptions, ScopedPreloaderStatus } from "./services/preloader";
export { createPreferenceStore, PreferenceStore } from "./services/preferences";
export type { PreferenceStoreBackend, PreferenceStoreOptions } from "./services/preferences";
export { consoleLogger } from "./services/logger";
export type { Logger } from "./services/logger";
export { Page } from "./page/page";
export type { NamedPageConstructor, PageConstructor, PageState, PageStateChangeDetail } from "./page/page";
export type { PageRunActionOptions } from "./page/page";
export { PageRegistry, registerPage } from "./page/registry";
export type { PageLoader, PageRegistryMountOptions } from "./page/registry";
export { page, setupPage } from "./page/setup-page";
export type { PageSetupContext } from "./page/setup-page";
export { Component } from "./component/component";
export type { ComponentOptions, ComponentRunActionOptions, ComponentStateChangeDetail } from "./component/component";
export { ComponentManager } from "./component/manager";
export type { ComponentManagerOptions } from "./component/manager";
export { ComponentRegistry, globalComponentRegistry, registerComponent } from "./component/registry";
export type {
  ComponentConstructor,
  ComponentState,
  NamedComponentConstructor
} from "./component/registry";
export { AssetService } from "./services/assets";
export type {
  AssetBundleOptions,
  AssetBundleResult,
  AssetDispose,
  AssetElement,
  AssetOptions,
  ScriptAssetInput,
  ScriptAssetOptions,
  StylesheetAssetInput,
  StylesheetAssetOptions
} from "./services/assets";
export { TransitionService } from "./services/transitions";
export type { SwapMode, SwapOptions, TransitionCallback, TransitionName } from "./services/transitions";
export {
  addDomParam,
  addElementParams,
  addFormParams,
  attr,
  closest,
  collectElementParams,
  collectFormParams,
  collectIncludedParams,
  data,
  delegate,
  escapeHtml,
  isNamedFormControl,
  mustQuery,
  query,
  queryAllSelfOrDescendants,
  querySelfOrDescendant,
  setClasses,
  setHidden
} from "./dom/helpers";
export type { DelegatedDomHandler, DomParams, FormParamOptions, StopDomListener } from "./dom/helpers";
export { createHttpClient, normalizeHttpError } from "./http/client";
export type { HttpClient, HttpClientOptions, HttpErrorHandler, HttpErrorInfo, HttpMethod, HttpRequestConfig, HttpResult } from "./http/client";
export { getCsrfToken, isStateChangingMethod } from "./http/csrf";
export { deleteCookie, getCookie, serializeCookie, setCookie } from "./http/cookies";
export type { CookieOptions, CookieSameSite } from "./http/cookies";
export { runAction, startActions } from "./actions/actions";
export type {
  ActionCompleteDetail,
  ActionConfirmHandler,
  ActionErrorDetail,
  ActionInvalidDetail,
  ActionParams,
  ActionRequestContextDetail,
  ActionSuccessDetail,
  ActionToggleDetail,
  RunActionOptions,
  StartActionsOptions
} from "./actions/actions";
export { ApiResponseAction, ResponseActionRunner } from "./actions/response-actions";
export type {
  CloseModalAction,
  DefaultApiFormResponse,
  DefaultApiResponse,
  FeedbackAction,
  FeedbackMode,
  HtmlSwap,
  RedirectAction,
  ReloadTableAction,
  ReplaceHtmlAction,
  ResponseAction,
  ResponseActionContext,
  ResponseFeedback
} from "./actions/response-actions";
export { getStimulusApplication, registerController, registerControllers } from "./stimulus/controllers";
export type { StimulusControllerDefinitions } from "./stimulus/controllers";
export * from "./i18n";
export {
  FINGERPRINT_HEADER,
  createFingerprintSender,
  deviceVisitorId
} from "./security/fingerprint";
export type { FingerprintSender, FingerprintSenderOptions } from "./security/fingerprint";
