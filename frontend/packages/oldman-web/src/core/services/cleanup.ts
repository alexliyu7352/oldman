import type { Logger } from "./logger";
import { consoleLogger } from "./logger";

export type CleanupCallback = () => void | Promise<void>;

export class CleanupRegistry {
  private callbacks: CleanupCallback[] = [];
  private completed = false;

  add(callback: CleanupCallback): CleanupCallback {
    if (this.completed) {
      throw new Error("Cannot add cleanup callback after registry has run");
    }

    this.callbacks.push(callback);
    return callback;
  }

  async run(logger: Logger = consoleLogger): Promise<void> {
    if (this.completed) return;
    this.completed = true;

    const callbacks = [...this.callbacks].reverse();
    this.callbacks = [];

    for (const callback of callbacks) {
      try {
        await callback();
      } catch (error) {
        logger.error("[oldman] cleanup callback failed", error);
      }
    }
  }
}
