# `oldman.web.messages`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Public browser user-message APIs.

Import with `from oldman.web.messages import <name>`.

## `add_message`

function · defined in `oldman.web.messages.flash`

```python
def add_message(request: Request, level: MessageLevel, content: str, *, format: MessageFormat=MessageFormat.TEXT) -> None
```

Append a translated message to middleware-owned request storage.

## `DashboardActivityAction`

class · defined in `oldman.web.messages.actions`

```python
class DashboardActivityAction(ResponseAction, tag='dashboard_activity', kw_only=True)
```

Add one non-persistent item to the Dashboard current-activity menu.

Members:

- `title: str | LazyTranslation`
- `description: str | LazyTranslation = ''`
- `tone: str = 'primary'`
- `icon: str | None = None`
- `href: str | None = None`
- `time: str | LazyTranslation | None = None`

## `error`

function · defined in `oldman.web.messages.flash`

```python
def error(request: Request, content: str) -> None
```

Add an escaped error message.

## `FlashMessage`

class · defined in `oldman.web.messages.flash`

```python
class FlashMessage(MsgspecModel, kw_only=True, frozen=True)
```

One translated message rendered in the next suitable page response.

Members:

- `level: MessageLevel`
- `content: str`
- `format: MessageFormat = MessageFormat.TEXT`

## `info`

function · defined in `oldman.web.messages.flash`

```python
def info(request: Request, content: str) -> None
```

Add an escaped informational message.

## `init_app`

function · defined in `oldman.web.messages._cookie_storage`

```python
def init_app(app: Sanic) -> None
```

Install signed Cookie flash storage and its Jinja global on one app.

## `MessageFormat`

class · defined in `oldman.web.messages.flash`

```python
class MessageFormat(StrEnum)
```

Whether a message is escaped text or explicitly trusted HTML.

## `MessageLevel`

class · defined in `oldman.web.messages.flash`

```python
class MessageLevel(StrEnum)
```

Visual severity of a one-time page message.

## `NotificationPresentation`

class · defined in `oldman.web.messages.notifications.payloads`

```python
class NotificationPresentation(StrEnum)
```

How an arriving notification may interrupt an online user.

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

## `success`

function · defined in `oldman.web.messages.flash`

```python
def success(request: Request, content: str) -> None
```

Add an escaped success message.

## `warning`

function · defined in `oldman.web.messages.flash`

```python
def warning(request: Request, content: str) -> None
```

Add an escaped warning message.

## Module `oldman.web.messages.paths`

The one rule for a link a message may point at.

Import with `from oldman.web.messages.paths import <name>`.

### `DANGEROUS_SCHEMES`

value · defined in `oldman.utils.http`

```python
DANGEROUS_SCHEMES = frozenset({'javascript', 'data', 'vbscript', 'file', 'blob'})
```

### `is_safe_link`

function · defined in `oldman.utils.http`

```python
def is_safe_link(value: object) -> bool
```

Return whether a link is safe to render into an anchor or hand to a browser navigation.

### `is_same_site_path`

function · defined in `oldman.utils.http`

```python
def is_same_site_path(value: object) -> bool
```

Return whether a value is safe to use as a server-side redirect target.
