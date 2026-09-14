import { Component } from "../core/component/component";
import { setHidden } from "../core/dom/helpers";

export interface CountdownCompleteDetail {
  target: Date;
}

const SECOND_MS = 1000;
const MINUTE_SECONDS = 60;
const HOUR_SECONDS = 60 * MINUTE_SECONDS;
const DAY_SECONDS = 24 * HOUR_SECONDS;

/** Render an ISO timestamp as a live days, hours, minutes and seconds countdown. */
export class Countdown extends Component {
  static readonly componentName = "countdown";
  private intervalId: number | null = null;
  private target: Date | null = null;

  override async mount(): Promise<void> {
    const value = this.root.dataset.omCountdownTarget;
    const timestamp = value ? Date.parse(value) : Number.NaN;
    if (!Number.isFinite(timestamp)) throw new Error("Countdown requires a valid data-om-countdown-target ISO timestamp");

    this.target = new Date(timestamp);
    if (this.renderRemaining(timestamp - Date.now())) {
      this.intervalId = this.timers.interval(() => this.tick(), SECOND_MS);
    }
  }

  override async unmount(): Promise<void> {
    this.stopTimer();
    this.target = null;
    delete this.root.dataset.omCountdownState;
  }

  private tick(): void {
    if (!this.target || this.renderRemaining(this.target.getTime() - Date.now())) return;
    this.stopTimer();
    this.emit<CountdownCompleteDetail>("om:countdown:complete", { target: this.target });
  }

  /** Return true while time remains so the caller knows whether to keep ticking. */
  private renderRemaining(remainingMs: number): boolean {
    const totalSeconds = Math.max(0, Math.ceil(remainingMs / SECOND_MS));
    this.write("days", Math.floor(totalSeconds / DAY_SECONDS));
    this.write("hours", Math.floor(totalSeconds % DAY_SECONDS / HOUR_SECONDS));
    this.write("minutes", Math.floor(totalSeconds % HOUR_SECONDS / MINUTE_SECONDS));
    this.write("seconds", totalSeconds % MINUTE_SECONDS);

    const running = totalSeconds > 0;
    this.root.dataset.omCountdownState = running ? "running" : "complete";
    const complete = this.root.querySelector<HTMLElement>("[data-om-countdown-complete]");
    if (complete) setHidden(complete, running);
    return running;
  }

  private write(part: string, value: number): void {
    const element = this.root.querySelector<HTMLElement>(`[data-om-countdown-${part}]`);
    if (element) element.textContent = String(value).padStart(2, "0");
  }

  private stopTimer(): void {
    if (this.intervalId === null) return;
    window.clearInterval(this.intervalId);
    this.intervalId = null;
  }
}
