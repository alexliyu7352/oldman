import type {
  ActionCompleteDetail,
  ActionErrorDetail,
  ActionInvalidDetail,
  ActionRequestContextDetail,
  ActionSuccessDetail,
  ActionToggleDetail
} from "./actions/actions";
import type { PageStateChangeDetail } from "./page/page";

export type StopCoreEventListener = () => void;

export interface CoreEventMap {
  "om:action:complete": ActionCompleteDetail;
  "om:action:error": ActionErrorDetail;
  "om:action:invalid": ActionInvalidDetail;
  "om:action:request": ActionRequestContextDetail;
  "om:action:success": ActionSuccessDetail;
  "om:action:toggle": ActionToggleDetail;
  "om:page:state": PageStateChangeDetail;
}

export type CoreEventName = keyof CoreEventMap;
export type CoreEvent<TEventName extends CoreEventName> = CustomEvent<CoreEventMap[TEventName]>;
export type CoreEventHandler<TEventName extends CoreEventName> = (event: CoreEvent<TEventName>) => void;

export function onCoreEvent<TEventName extends CoreEventName>(
  target: Document | HTMLElement,
  eventName: TEventName,
  handler: CoreEventHandler<TEventName>
): StopCoreEventListener {
  const listener = (event: Event) => {
    handler(event as CoreEvent<TEventName>);
  };

  target.addEventListener(eventName, listener);
  return () => target.removeEventListener(eventName, listener);
}
