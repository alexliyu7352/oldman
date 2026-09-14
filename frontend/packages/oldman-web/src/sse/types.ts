/** Final translated payload sent before a guarded SSE connection closes. */
export interface SessionInvalidatedPayload {
  login_url: string;
  message: string;
  title: string;
}

/** Receives one parsed JSON payload and its original browser event. */
export type EventStreamPayloadHandler<TPayload> = (
  payload: TPayload,
  event: MessageEvent<string>
) => void;

/** Observes native EventSource connection lifecycle events. */
export type EventStreamLifecycleHandler = (event: Event) => void;

/** Idempotently removes one handler from its EventStreamClient. */
export type StopEventStreamHandler = () => void;
