import { Feedback, type FeedbackOptions } from "../components/feedback";

export type DashboardFeedbackOptions = FeedbackOptions;

/** Shared Dashboard/Admin SweetAlert theme adapter. */
export class DashboardFeedback extends Feedback {
  protected override defaultOptions(): FeedbackOptions {
    return {
      buttonsStyling: false,
      customClass: {
        actions: "gap-2",
        cancelButton: "om-button om-button-danger mt-2",
        confirmButton: "om-button om-button-primary mt-2",
        denyButton: "om-button om-button-soft-info mt-2"
      },
      showCloseButton: true
    };
  }
}
