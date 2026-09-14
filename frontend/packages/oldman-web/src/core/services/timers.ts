import type { CleanupRegistry } from "./cleanup";

export class TimerService {
  constructor(private readonly cleanup: CleanupRegistry) {}

  timeout(callback: () => void, delay: number): number {
    const id = window.setTimeout(callback, delay);
    this.cleanup.add(() => window.clearTimeout(id));
    return id;
  }

  interval(callback: () => void, delay: number): number {
    const id = window.setInterval(callback, delay);
    this.cleanup.add(() => window.clearInterval(id));
    return id;
  }
}
