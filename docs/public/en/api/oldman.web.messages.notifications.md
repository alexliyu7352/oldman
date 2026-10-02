# `oldman.web.messages.notifications`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Public strong types for persistent and realtime user notifications.

Import with `from oldman.web.messages.notifications import <name>`.

## `init_app`

function · defined in `oldman.web.messages.notifications.runtime`

```python
def init_app(app: Sanic, *, url_prefix: str='', login_url: str | None=None) -> NotificationRoutes
```

Install shared endpoints once and return shared and host-wrapper URLs.

## `NOTIFICATION_CREATED_EVENT`

value · defined in `oldman.web.messages.notifications.service`

```python
NOTIFICATION_CREATED_EVENT = 'oldman.notifications.created'
```

## `NOTIFICATION_PUSH_EVENT`

value · defined in `oldman.web.messages.notifications.service`

```python
NOTIFICATION_PUSH_EVENT = 'oldman.notifications.push'
```

## `NOTIFICATION_SYNC_EVENT`

value · defined in `oldman.web.messages.notifications.service`

```python
NOTIFICATION_SYNC_EVENT = 'oldman.notifications.sync'
```

## `NotificationCreatedPayload`

class · defined in `oldman.web.messages.notifications.payloads`

```python
class NotificationCreatedPayload(TranslatableMsgspecModel, kw_only=True, frozen=True)
```

Notify an online browser that one persistent notification was created.

Members:

- `notification_id: int`
- `notification: NotificationPayload`
- `created_at: datetime`

## `NotificationPayload`

class · defined in `oldman.web.messages.notifications.payloads`

```python
class NotificationPayload(TranslatableMsgspecModel, kw_only=True, frozen=True)
```

Versioned untranslated content stored in the database and sent to SSE.

Members:

- `version: int = 1`
- `title: LazyTranslation`
- `body: LazyTranslation | None = None`
- `level: MessageLevel = MessageLevel.INFO`
- `format: MessageFormat = MessageFormat.TEXT`
- `presentation: NotificationPresentation = NotificationPresentation.NONE`
- `href: str | None = None`
- `icon: str | None = None`

## `NotificationPresentation`

class · defined in `oldman.web.messages.notifications.payloads`

```python
class NotificationPresentation(StrEnum)
```

How an arriving notification may interrupt an online user.

## `NotificationPushPayload`

class · defined in `oldman.web.messages.notifications.payloads`

```python
class NotificationPushPayload(TranslatableMsgspecModel, kw_only=True, frozen=True)
```

Carry one non-persistent notification to an online browser.

Members:

- `notification: NotificationPayload`

## `NotificationRoutes`

class · defined in `oldman.web.messages.notifications.runtime`

```python
class NotificationRoutes
```

Stable notification URLs derived for one host prefix.

Members:

- `topbar_url: str`
- `read_url: str`
- `delete_url: str`
- `center_url: str`

## `notifications`

value · defined in `oldman.web.messages.notifications.service`

```python
notifications = Notifications()
```

## `NotificationState`

class · defined in `oldman.web.messages.notifications.payloads`

```python
class NotificationState(StrEnum)
```

Read-state filter accepted by notification queries.

## `NotificationSyncPayload`

class · defined in `oldman.web.messages.notifications.payloads`

```python
class NotificationSyncPayload(MsgspecModel, kw_only=True, frozen=True)
```

Tell browsers how many notification rows changed state.

Members:

- `changed_count: int`

## `render_center_content`

function · defined in `oldman.web.messages.notifications.rendering`

```python
async def render_center_content(request: Request, *, user_id: int) -> Markup
```

Parse this request and render one translated notification-center body.

## `render_topbar_fragment`

function · defined in `oldman.web.messages.notifications.rendering`

```python
async def render_topbar_fragment(request: Request, *, user_id: int) -> Markup
```

Render one recipient's translated topbar fragment.

## Module `oldman.web.messages.notifications.apps`

Installable persistent notifications application metadata.

Import with `from oldman.web.messages.notifications.apps import <name>`.

### `app`

value · defined in `oldman.web.messages.notifications.apps`

```python
app = NotificationsAppConfig()
```

### `NotificationsAppConfig`

class · defined in `oldman.web.messages.notifications.apps`

```python
class NotificationsAppConfig(AppConfig)
```

Describe the framework-owned persistent notifications application.

## Module `oldman.web.messages.notifications.models`

Persistent per-user notification model.

Import with `from oldman.web.messages.notifications.models import <name>`.

### `Notification`

class · defined in `oldman.web.messages.notifications.models`

```python
class Notification(DatabaseModel)
```

Store one unread or read notification owned by a concrete User row.

Members:

- `id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)`
- `recipient_id: Mapped[int] = mapped_column(Integer, ForeignKey('oldman_user.id', ondelete='CASCADE'), nullable=False)`
- `payload: Mapped[bytes] = mapped_column(LargeBinary(MAX_NOTIFICATION_PAYLOAD_SIZE), nullable=False)`
- `created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=naive_utcnow, server_default=text('CURRENT_TIMESTAM…`
- `read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)`

## Module `oldman.web.messages.notifications.payloads`

Strong binary payloads shared by notification storage and browser events.

Import with `from oldman.web.messages.notifications.payloads import <name>`.

### `MAX_NOTIFICATION_PAYLOAD_SIZE`

value · defined in `oldman.web.messages.notifications.payloads`

```python
MAX_NOTIFICATION_PAYLOAD_SIZE = 32 * 1024
```

## Module `oldman.web.messages.notifications.service`

Database-backed user notifications and best-effort browser delivery.

Import with `from oldman.web.messages.notifications.service import <name>`.

### `Notifications`

class · defined in `oldman.web.messages.notifications.service`

```python
class Notifications
```

Provide the sole database and realtime notification business API.

Constructor:

```python
Notifications(*, _publisher_factory: Callable[[], SSEPublisher]=SSEPublisher.from_settings) -> None
```

Members:

- `async def create(*, user_id: int, title: str | LazyTranslation, body: str | LazyTranslation | None=None, level: MessageLevel=MessageLevel.INFO, format: MessageFormat=MessageFormat.TEXT, presentation: NotificationPresentation=NotificationPresentation.NONE, href: str | None=None, icon: str | None=None) -> Notification` — Persist one notification, then best-effort publish its created event.
- `async def push(*, user_id: int, title: str | LazyTranslation, body: str | LazyTranslation | None=None, level: MessageLevel=MessageLevel.INFO, format: MessageFormat=MessageFormat.TEXT, presentation: NotificationPresentation=NotificationPresentation.TOAST, href: str | None=None, icon: str | None=None) -> bool` — Best-effort publish one temporary notification without database writes.
- `async def list_for_user(user_id: int, *, state: NotificationState=NotificationState.ALL, page: int=1, page_size: int=20) -> PageResult[Notification]` — Return one recipient-scoped, stably ordered page.
- `async def topbar_for_user(user_id: int, *, limit: int=5) -> list[Notification]` — Return the recipient's newest unread rows.
- `async def unread_count(user_id: int) -> int` — Count unread rows for exactly one recipient.
- `async def get_for_user(user_id: int, notification_id: int) -> Notification | None` — Return a row only when both recipient and id match.
- `async def mark_read(user_id: int, notification_ids: Sequence[int]) -> int` — Mark selected recipient rows read and return the changed count.
- `async def mark_all_read(user_id: int) -> int` — Mark every unread row for one recipient and return the changed count.
- `async def delete(user_id: int, notification_ids: Sequence[int]) -> int` — Delete selected recipient rows and return the changed count.
