# `oldman.web.api`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Public browser response protocol.

Import with `from oldman.web.api import <name>`.

## `accepts_html_form_response`

function · defined in `oldman.web.api.forms`

```python
def accepts_html_form_response(request: Any) -> bool
```

A fragment consumer (Turbo, fetch) asks for HTML and not for JSON.

## `accepts_json_form_response`

function · defined in `oldman.web.api.forms`

```python
def accepts_json_form_response(request: Any) -> bool
```

The mounted Form component asks for the JSON protocol through its Accept header.

## `ApiErrorCode`

class · defined in `oldman.web.api.enums`

```python
class ApiErrorCode(IntEnum)
```

统一 API 响应错误码。

## `ApiResponseAction`

class · defined in `oldman.web.api.enums`

```python
class ApiResponseAction(StrEnum)
```

框架内置响应动作。

## `CloseModalAction`

class · defined in `oldman.web.api.actions`

```python
class CloseModalAction(ResponseAction, tag=ApiResponseAction.CLOSE_MODAL.value, kw_only=True)
```

Close an explicit or source-adjacent modal.

## `DefaultApiFormResponse`

class · defined in `oldman.web.api.responses`

```python
class DefaultApiFormResponse(DefaultApiResponse)
```

API response carrying first errors for concrete form fields.

Members:

- `errors: dict[str, str | LazyTranslation] = msgspec.field(default_factory=dict)`

## `DefaultApiResponse`

class · defined in `oldman.web.api.responses`

```python
class DefaultApiResponse(TranslatableMsgspecModel, kw_only=True)
```

Business result with ordered browser actions.

Members:

- `error_code: int | ApiErrorCode = ApiErrorCode.OK`
- `message: str | LazyTranslation = ''`
- `data: dict[Any, Any] = msgspec.field(default_factory=dict)`
- `actions: list[ResponseAction] = msgspec.field(default_factory=list)`

## `feedback_response`

function · defined in `oldman.web.api.forms`

```python
def feedback_response(message: Message, *, text: Message | None=None, feedback_target: str | None=None, actions: Sequence[ResponseAction]=())
```

Success that keeps the page: a Feedback toast, then `actions` in order.

## `FeedbackAction`

class · defined in `oldman.web.api.actions`

```python
class FeedbackAction(ResponseAction, tag=ApiResponseAction.FEEDBACK.value, kw_only=True)
```

Show one plain-text toast or alert.

Members:

- `mode: FeedbackMode = FeedbackMode.TOAST`
- `title: str | LazyTranslation`
- `text: str | LazyTranslation | None = None`
- `icon: str | None = None`

## `FeedbackMode`

class · defined in `oldman.web.api.enums`

```python
class FeedbackMode(StrEnum)
```

用户反馈的显示方式。

## `form_error_response`

function · defined in `oldman.web.api.forms`

```python
def form_error_response(message: Message, *, errors: Mapping[str, Message] | None=None, error_code: ApiErrorCode=ApiErrorCode.FORM_INVALID, status: int=200)
```

A business error the Form shows inline: HTTP 200, a non-zero error code and concrete field errors only.

## `form_invalid_response`

function · defined in `oldman.web.api.forms`

```python
async def form_invalid_response(request: Any, form: Any, *, fragment: FragmentSource | None=None, page: Callable[[], Awaitable[Any]] | None=None, status: int=422)
```

A form that failed validation, in the shape the client asked for.

## `form_response`

function · defined in `oldman.web.api.forms`

```python
def form_response(message: Message='', *, actions: Sequence[ResponseAction]=(), errors: Mapping[str, Message] | None=None, error_code: ApiErrorCode=ApiErrorCode.OK, status: int=200)
```

One JSON Form payload; the building block the helpers below share.

## `form_saved_response`

function · defined in `oldman.web.api.forms`

```python
def form_saved_response(message: Message, *, url: str, delay_ms: int=0, feedback_target: str | None=None, actions: Sequence[ResponseAction]=())
```

Success that leaves the page: Feedback, then `actions`, then a redirect (after `delay_ms`).

## `form_success_response`

function · defined in `oldman.web.api.forms`

```python
def form_success_response(request: Any, redirect_url: str, *, status: int=303)
```

After a save: the JSON client receives a RedirectAction, a plain browser a redirect.

## `HtmlSwap`

class · defined in `oldman.web.api.enums`

```python
class HtmlSwap(StrEnum)
```

HTML 替换范围。

## `modal_close_footer`

function · defined in `oldman.web.api.forms`

```python
def modal_close_footer(label: Message)
```

The footer of a read-only modal: one secondary button that closes it.

## `modal_not_found_response`

function · defined in `oldman.web.api.forms`

```python
def modal_not_found_response(title: Message, message: Message, *, status: int=200)
```

The modal payload for an object that is gone: the modal title and one muted paragraph.

## `modal_response`

function · defined in `oldman.web.api.forms`

```python
def modal_response(title: Message, *, html: Markup | str | None=None, body: Markup | str | None=None, footer: Markup | str | None=None, close_label: Message | None=None, status: int=200)
```

The payload a remote modal expects: its title plus the content to put inside it.

## `modal_success_response`

function · defined in `oldman.web.api.forms`

```python
def modal_success_response(message: Message, *, table_target: str, text: Message | None=None, feedback_target: str | None=None, actions: Sequence[ResponseAction]=())
```

Success inside a row-action modal: Feedback, `actions`, close the modal, reload the table.

## `RedirectAction`

class · defined in `oldman.web.api.actions`

```python
class RedirectAction(ResponseAction, tag=ApiResponseAction.REDIRECT.value, kw_only=True)
```

Navigate after an optional non-negative delay.

Members:

- `url: str`
- `delay_ms: Annotated[int, msgspec.Meta(ge=0)] = 0`

## `ReloadTableAction`

class · defined in `oldman.web.api.actions`

```python
class ReloadTableAction(ResponseAction, tag=ApiResponseAction.RELOAD_TABLE.value, kw_only=True)
```

Reload one mounted table.

Members:

- `target: str`

## `ReplaceHtmlAction`

class · defined in `oldman.web.api.actions`

```python
class ReplaceHtmlAction(ResponseAction, tag=ApiResponseAction.REPLACE_HTML.value, kw_only=True)
```

Replace one page-scoped HTML target.

Members:

- `html: str`
- `swap: HtmlSwap | None = None`

## `ResponseAction`

class · defined in `oldman.web.api.actions`

```python
class ResponseAction(TranslatableMsgspecModel, tag_field='action', kw_only=True, omit_defaults=True)
```

Base contract for one ordered browser action.

Members:

- `target: str | None = None`
- `data: Any = None`
