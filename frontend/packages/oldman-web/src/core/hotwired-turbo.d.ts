declare module "@hotwired/turbo" {
  export const session: {
    linkPrefetchObserver: {
      started: boolean;
      start(): void;
      stop(): void;
    };
  };
  export function start(): void;
}
