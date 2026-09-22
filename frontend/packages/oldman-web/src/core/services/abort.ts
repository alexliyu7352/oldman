import { isCancel } from "axios";

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

/**
 * 判断错误是否只是一次取消。页面卸载会先 abort 页面信号，在途请求随即拒绝，
 * 调用方必须把它当作正常退出，而不是业务错误。axios 的 CanceledError 与 DOM 自身的
 * AbortError 都要认，两者会在同一条链路上出现。
 */
export function isCanceledError(error: unknown): boolean {
  if (isCancel(error)) return true;
  if (!error || typeof error !== "object") return false;
  const record = error as { code?: unknown; name?: unknown };
  return record.code === "ERR_CANCELED" || record.name === "CanceledError" || record.name === "AbortError";
}
