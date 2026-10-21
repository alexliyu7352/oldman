# Page messages, feedback, and notifications

| What users see | Entry point | Storage |
| --- | --- | --- |
| Page-top notice after redirect | `oldman.web.messages.success/error/add_message` | Short-lived signed Cookie |
| Form top message and field errors | Form/DefaultApiFormResponse | Current response |
| Toast/dialog requested by the current response | `FeedbackAction` | Current ordered actions |
| Personal notification with read state | `notifications.create()` | Database, then best-effort SSE delivery |
| Temporary online toast/dialog | `notifications.push()` | SSE only, without persistence |

Task-process control messages and NATS are outside this table; see [Processes and background tasks](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/background.md) and [Redis and NATS providers](providers.md). Browser Feedback does not automatically create database notifications.

## Cookie page messages

Set `web.messages.enabled: true` and prepare `web.security.secret_key` through service `settings sync`. WebApplication installs middleware and Jinja `messages` internally; normally do not call `messages.init_app()` again. If Admin is installed and YAML omits the switch, settings init/sync adds true. Explicit false is retained; loading configuration alone does not enable it.

The actual four-message endpoint in EPG [apps/examples/views/messages.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/messages.py):

```python
@router.post("/examples/messages/page/multiple", name="example_message_multiple")
@csrf_protect()
@login_required()
async def example_message_multiple(request: Request):
    """Store all four levels in insertion order, then redirect."""
    success(request, str(_("The database changes were saved.")))
    info(request, str(_("The background import is still running.")))
    warning(request, str(_("Two optional records were skipped.")))
    error(request, str(_("One required record could not be imported.")))
    return redirect_response("/examples/messages/page", status=303)
```

This is a complete function in an existing view module, not a standalone module. `router` comes from `oldman.web`; success/info/warning/error from `oldman.web.messages`; `_` is gettext_lazy; and `str()` resolves translation in the current request. The original file also imports Request, redirect_response, CSRF, and `login_required` (`oldman.web.auth`). [messages/page.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/messages/page.html) submits a native CSRF-protected POST and follows 303. These four texts demonstrate levels/order without actually importing or writing data; the wording is not a business result.

All four shortcuts, `success/info/warning/error(request, content)`, accept **final strings**. Call gettext in the current request first when translation is needed. The typed `MessageLevel` values are success/info/warning/error.

Text is escaped by default. The same demo module's trusted-HTML endpoint is:

```python
@router.post("/examples/messages/page/trusted-html", name="example_message_trusted_html")
@csrf_protect()
@login_required()
async def example_message_trusted_html(request: Request):
    """Store one fixed server-authored HTML message, never browser input."""
    content = "<strong>{}</strong> {}".format(
        escape(str(_("Trusted server HTML"))),
        escape(str(_("Only fixed server markup uses this mode."))),
    )
    add_message(
        request,
        MessageLevel.INFO,
        content,
        format=MessageFormat.HTML,
    )
    return redirect_response("/examples/messages/page", status=303)
```

escape comes from markupsafe. Retain only server-authored tags and escape dynamic text first. The following is a template-extension API example, not another demo template. It can display all messages together with your chosen layout.

```jinja
{% if messages %}
  {% for message in messages %}
    <div role="alert" class="om-alert om-alert-{{ message.level }}">
      {% if message.format == "html" %}{{ message.content | safe }}{% else %}{{ message.content }}{% endif %}
    </div>
  {% endfor %}
{% endif %}
```

The default fragment is `oldman/messages/flash_message.html`, already included by shared Dashboard base. Override it to change display without Jinja tags or `get_messages(request)`. It is not a toast and does not enter the notification center.

### Consumption and limits

- Supports anonymous browsers without Session Redis, user IDs, or databases; only reuses Cookie security attributes from Session settings.
- Cookie name is `oldman_messages`, path `/`, maximum lifetime 3600 seconds. Unconsumed messages without additions do not renew it; new pending messages trigger rewriting/renewal.
- `if messages` and `len(messages)` do not consume. Beginning iteration marks the current snapshot consumed; response middleware deletes/rewrites the Cookie. Messages added after iteration remain for a later response.
- **There is no browser acknowledgment that HTML was displayed successfully.** A render error after template iteration does not roll back consumption; middleware does not restore messages based on response status. Do not use this for information requiring guaranteed delivery.
- Cookie values are limited to 2048 bytes, decompressed content to 64 KiB. Overflow discards oldest whole messages with a warning. One oversized message may also be discarded; HTML is not truncated.
- HMAC prevents tampering without encryption, so store no secrets. Invalid/tampered Cookies are ignored and cleared.
- Workers sharing a key can read/write, but concurrent responses in one browser may still overwrite Cookies. This is neither a cross-request transaction nor an exactly-once queue.
- Calling message functions while disabled explicitly raises an initialization error rather than silently dropping messages.

## Form and current-response feedback

Form owns its dedicated `data-om-form-message` and field errors, displaying them before actions. Fields show only their first error. Ordered `feedback` Actions invoke current Page Feedback. Business errors do not prevent actions, and network errors do not fabricate Form messages. See [Browser responses and ordered actions](responses.md) for the complete protocol; do not turn these temporary results into database notifications.

`DashboardActivityAction` records temporary browser-shell activity, not durable personal notifications. Its DOM section differs from notification previews and uses no database read_at. After a change, `recent_activity(request, title, description, *, tone, icon, href)` (`oldman.web.messages.actions`) supplies an entry timestamped "Just now". User/role management flows both use it.

## Installing persistent notifications

Service `apps` must include at least `oldman.auth` and `oldman.web.messages.notifications`, then apply supplied migrations through [Project database migrations](migrations.md). Admin additionally installs `oldman.apps.admin`. Needing User does not make the notification App install Auth automatically.

`oldman_notification.recipient_id` is a real foreign key to `oldman_user.id`; deleting users cascades to their notifications. Title/body and presentation parameters are MsgPack bytes in LargeBinary, not JSON string columns. Business payloads are limited to 32 KiB. Tables are not secretly created during startup.

The actual sending endpoint is EPG [example_notification_send](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/notifications.py), POST `/examples/notifications/send`. It reads the current user from dashboard_session rather than accepting browser user_id. After checking mode/level/presentation/content_mode/title and other fields, it enters this original persistence branch:

```python
        if mode == "persistent":
            row = await notifications.create(
                user_id=user_id,
                title=title,
                body=body,
                level=level,
                format=message_format,
                presentation=presentation,
                href=href,
                icon=icon,
            )
            data: dict[str, object] = {"mode": mode, "notification_id": row.id}
```

Import notifications/NotificationPresentation from `oldman.web.messages.notifications` and MessageLevel/MessageFormat from `oldman.web.messages`. Other variables come from earlier input validation in this function. Do not copy the branch and trust unchecked dictionaries. `trusted_html` uses fixed `_TRUSTED_BODY` from the file and ignores browser body; `text` retains user content and displays it as text. The corresponding [generator template](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/notifications/generator.html) explicitly shows both choices.

The same function's temporary branch calls `notifications.push` and returns `data={"mode": mode, "delivered": delivered}`. delivered is only the Redis publish boolean, not user-delivery acknowledgment. Both branches ultimately return DefaultApiResponse through general data-om-action submission. Actual toast/modal presentation comes from user SSE events, not a fabricated HTTP-response notification.

`notifications` is a public process-wide service obtaining its publisher on demand. Service bootstrap, notification App installation, and model loading must already be complete. Background processes need no Sanic request. User language is read during SSE/page rendering rather than background create.

`create(*, user_id, title, body=None, level=INFO, format=TEXT, presentation=NONE, href=None, icon=None)` returns a committed Notification. It uses **its own database transaction** rather than joining another Session held by the caller. Complete the related business transaction before calling. There is no outbox or database/Redis atomic transaction.

title/body accept ordinary untranslated source strings or `LazyTranslation`. Ordinary strings are also wrapped for lazy translation. Explicitly use `_('literal')` for fixed extraction entries. Lazy parameters support JSON scalars only. `presentation` is NONE/TOAST/MODAL; NONE still enters the center without interrupting online users.

**Titles are always text**. `format=HTML` only displays the body as trusted HTML. String variables in a lazy body are escaped, while developers own HTML-template-body safety. Do not use unchecked user input as an HTML source template or expect tags in ordinary TEXT to become HTML. `href` accepts only safe absolute same-site paths. icon is a single `ri-*`, `mdi-*`, `bx-*`, `bxs-*`, or `bxl-*` class and must also enter the application build; see [Frontend assets, styles, icons, and translation](assets.md).

After database success, create publishes `oldman.notifications.created`. Redis unavailability retains the notification and logs network publishing failure. Oversized SSE envelopes also log without undoing the database. Offline browsers receive no replayed toast but can later read the center. Do not repeat create just because no toast appeared.

Temporary delivery uses `await notifications.push(...) -> bool` with the same parameters, default TOAST, and no NONE. It requires SSE enabled and the notification App registered. It writes no database record, center entry, or offline history. False indicates network publishing failure; True is not browser acknowledgment.

## Queries and read operations

All interfaces isolate users. Views must obtain user_id from trusted Sessions/permission decorators rather than treating request JSON recipients as current-user identity.

| Asynchronous method | Return value and constraints |
| --- | --- |
| `list_for_user(user_id, *, state=ALL, page=1, page_size=20)` | PageResult, page_size 1–100, descending created_at/id |
| `topbar_for_user(user_id, *, limit=5)` | Latest unread preview, limit 1–20; not every unread notification |
| `unread_count(user_id)` | Unread count |
| `get_for_user(user_id, notification_id)` | Current user's record or None |
| `mark_read(user_id, notification_ids)` | Number actually changed |
| `mark_all_read(user_id)` | Number actually changed |
| `delete(user_id, notification_ids)` | Number actually deleted |

`NotificationState.ALL/UNREAD/READ` is a StrEnum. After committing, mutations best-effort publish `oldman.notifications.sync`, prompting other tabs to reload topbar HTML. There is no separate notification-specific subscription service.

## Dashboard/Admin wiring

Admin is already wired: installing the notification App supplies `/admin/user-notifications` and shared action endpoints; enabling SSE supplies `/admin/user-events`, using Admin sign-in permissions.

Business dashboards install **notification HTTP operations**, not generic SSE routes, through `oldman.web.messages.notifications.init_app(app, *, url_prefix="", login_url=None) -> NotificationRoutes`. Unsigned-in browsers redirect to `login_url`, defaulting to site `web.account.login_url`. Reinstallation under the same prefix returns the first result. `installed_routes(app, url_prefix="")` retrieves installed URLs or None. Returned fields include topbar_url/read_url/delete_url/center_url:

- GET `/user-notifications/topbar` returns shared preview HTML.
- POST `/user-notifications/read` accepts `{"ids":[1,2]}` or `{"all":true}`.
- POST `/user-notifications/delete` accepts only `{"ids":[1,2]}`.
- GET `/user-notifications/<id>/open` verifies ownership, marks read, then redirects with 303 to href or the center.

These endpoints require Sessions, CSRF, and the template environment. Writes use CSRF. Invalid requests currently return HTTP 400; authentication/authorization follow shared security handling rather than fabricated success.

**Center shell page**: pass the `init_app()` result to `AccountFlow(notification_routes=...)`, which installs the center at `center_url` (page `user_notifications`, context `notification_center_content`); see [Web requests, templates, and permissions](web.md#ready-made-account-flows). Without `AccountFlow`, define it in the application: call `await render_center_content(request, user_id=user_id)` from a protected view and pass the result to a template inheriting your Dashboard base. `init_app()` does not choose business layouts. Shared `oldman/messages/notifications/center_content.html` already provides filtering, pagination, mark-selected/all-read, and deletion protocols. Do not duplicate controllers.

The topbar uses shared `dashboard_topbar` with `user_notification_urls={"topbar": routes.topbar_url, "center": routes.center_url}`. DashboardPage requests the latest preview on initialization, then refreshes on SSE created/sync and reconnection open. Previews show at most five clickable entries without bulk checkboxes. Displaying a toast does not mark read; opening or explicit marking does.

Wire user SSE routes and `<meta name="oldman-user-events-url">` according to [SSE and WebSocket](sse.md). Reuse DashboardPage notification/Feedback/connection handling rather than listening to Redis, parsing binary messages, copying notification DOM, or adding an independent subscriber.

<!-- source: zh/developers/messages.md @ c47d6711 -->
