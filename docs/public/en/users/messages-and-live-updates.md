# User messages and realtime updates

Don't put all messages in the notification center. The choice depends on whether the user still needs to find it later, not on whether it looks like a toast or page text.

First follow [Run EPG Dashboard Demo](getting-started.md) to prepare configuration, migrations, fixtures, an account, and the frontend, then sign in to your own demo. These pages already exist; no separate reporting service is needed for this chapter. See the [Page messages, feedback, and notifications](../developers/messages.md) for source and backend calls.

## Redirect after saving: flash messages

Enable `web.messages.enabled`, call `messages.success(request, "Saved")` after business success, then return a 303 redirect. Shared dashboard pages display messages automatically. Ordinary templates explicitly include `oldman/messages/flash_message.html` or iterate over `messages` themselves.

You can add multiple messages and render them all at once. They use signed Cookies, without Redis or a sign-in requirement. Capacity is limited, concurrent responses may overwrite them, and delivery is not acknowledged. Do not use them for long reports or important records. See [Page messages, feedback, and notifications](../developers/messages.md#cookie-page-messages) for HTML, translation, and consumption rules.

Use Form's message/errors when a form does not redirect. For a toast or modal in the current request, return `FeedbackAction` following the [Browser responses and ordered actions](../developers/responses.md), without writing a database notification.

Open `/examples/messages/page`: submit a single input, and tags display as text. Click “Show four messages”; the next page displays four severity levels in order at the top, without repeating them on refresh. The trusted HTML button sends only fixed server tags and displays bold text. The four messages demonstrate severity levels; they do not import data. `/examples/messages/feedback` instead demonstrates toasts, alerts, confirmation, and input for the current request. These two types do not replace each other.

## Background task completion: personal notifications

Install `oldman.auth` and `oldman.web.messages.notifications` in services sending and receiving notifications, sync configuration, and run `oldman db migrate`. For online alerts, configure Redis and the channel prefix following [SSE and WebSocket](../developers/sse.md#cross-process-configuration).

Call `notifications.create(user_id=..., title=..., body=...)` after the business transaction commits successfully. By default the notification enters the center without a modal; the online top bar still updates. Add `presentation=NotificationPresentation.TOAST` or MODAL for an additional online alert. The recipient ID must come from an object allowed by business rules. Do not let anonymous callers send arbitrary notifications to others.

Use lazy translation `_('Report ready')` in background work; do not guess the user's language and translate early. HTML is only for explicitly HTML bodies; titles are text.

Admin already wires the center, top bar, and user event routes. Business dashboards use shared notification interfaces, template bodies, and DashboardPage, without copying Admin's private implementation. Follow [Page messages, feedback, and notifications](../developers/messages.md#dashboardadmin-wiring) to add the host's center page, top bar URL, and user SSE meta.

Verify creating a notification while the user is offline and finding it in the center after sign-in; creating an online toast notification with an alert and top bar update; marking a notification as read by clicking it; and preventing another user from seeing it. A Redis publish log alone does not establish success.

Start at `/examples/notifications/generator`: choose persistence, presentation, and severity, then enter a title. Text mode uses the entered body; trusted HTML mode uses a fixed server body instead. Choose a single icon class such as `mdi-check-circle-outline` or `bx-error-circle`, rather than two space-separated classes. After sending, open `/user-notifications` to find the actual record. `/examples/notifications/center` provides instructions, not a second notification center. `/notifications` is EPG's business records page, not this personal notification center either.

## Alert only currently online users

Use `notifications.push()`. It does not write to the database or appear in the center; offline delivery is lost. It suits transient status messages, rather than error reports or to-dos that must persist. It uses the same user SSE connection, without another route or notification subscriber.

In the generator, select temporary and toast/modal. Temporary with “Notification center only” returns a visible business error without silently persisting. `/examples/notifications/realtime` also provides “Persist and deliver” and “Push online-only modal” buttons. The latter adds neither database records nor unread counts. The recipient is fixed to the current signed-in user; the browser is not authorized to send arbitrarily to others. Offline delivery and cross-user isolation checks need your own second account or background call; the generator does not provide those inputs.

## Realtime values are not notifications

Server bandwidth, task status, and chart values use ordinary `MsgspecModel` events delivered to pages through SSE. Page updates DOM/charts by business fields without creating Notification objects. Independent background processes use `SSEPublisher`; simple data computed within the current request uses `stream.send()` directly.

Start with the [SSE and WebSocket](../developers/sse.md#direct-output-from-the-current-request). To update Tables, use the [Realtime page guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/realtime.md). Table already outputs stable primary keys and column names. Changing one number does not require refreshing the entire table or adding a separate SSE Table component.

SSE provides best-effort delivery; fetch the current snapshot on reconnection. Do not use it to deliver the only copy of an important business result. Multiple identical connections or one EventSource per row add unnecessary overhead.

<!-- source: zh/users/messages-and-live-updates.md @ 60ab2b58 -->
