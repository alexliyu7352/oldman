/** Cancel waiting without pretending to cancel the underlying import or Promise. */
export function abortable<T>(promise: Promise<T>, signal?: AbortSignal, onAbort?: () => void): Promise<T> {
  if (!signal) return promise;
  return new Promise<T>((resolve, reject) => {
    const cancel = () => {
      onAbort?.();
      reject(abortError());
    };
    if (signal.aborted) cancel();
    else signal.addEventListener("abort", cancel, { once: true });
    // Observe late rejections even when cancellation has already won.
    promise.then(
      (value) => {
        signal.removeEventListener("abort", cancel);
        resolve(value);
      },
      (error) => {
        signal.removeEventListener("abort", cancel);
        reject(error);
      }
    );
  });
}

/** Use the browser's standard cancellation error across UI lifecycle callers. */
export function abortError(): DOMException {
  return new DOMException("The operation was aborted", "AbortError");
}
