# `oldman.mail`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Outgoing mail: django.core.mail's shape, async, on the stdlib email package and aiosmtplib.

Import with `from oldman.mail import <name>`.

## `Attachment`

class · defined in `oldman.mail.message`

```python
class Attachment(NamedTuple)
```

One attachment: a file name, its content (bytes, or text for `text/*`) and a MIME type.

Members:

- `filename: str`
- `content: bytes | str`
- `mimetype: str`

## `BaseEmailBackend`

class · defined in `oldman.mail.backends.base`

```python
class BaseEmailBackend
```

Base class for outgoing mail backends.

Constructor:

```python
BaseEmailBackend(*, fail_silently: bool=False, **options: Any) -> None
```

Members:

- `async def open() -> bool` — Open a connection; return True when this call created one (so the caller closes it).
- `async def close() -> None` — Close the connection opened by `open()`, if any.
- `async def send_messages(messages: Sequence[EmailMessage]) -> int` — Send every message and return the number delivered to the transport.

## `EmailMessage`

class · defined in `oldman.mail.message`

```python
class EmailMessage
```

A plain-text message with optional attachments; `send()` hands it to a backend.

Constructor:

```python
EmailMessage(subject: str='', body: str='', from_email: str | None=None, to: Sequence[str] | None=None, bcc: Sequence[str] | None=None, connection: BaseEmailBackend | None=None, attachments: Sequence[Attachment | tuple[str, bytes | str, str | None]] | None=None, headers: Mapping[str, str] | None=None, cc: Sequence[str] | None=None, reply_to: Sequence[str] | None=None) -> None
```

Members:

- `def get_connection(fail_silently: bool=False) -> BaseEmailBackend` — Return the message's backend, creating the configured one on first use.
- `def recipients() -> list[str]` — Every envelope recipient: To, then Cc, then Bcc.
- `def attach(filename: str, content: bytes | str, mimetype: str | None=None) -> None` — Add an attachment; the MIME type is guessed from the file name when not given.
- `def attach_file(path: str | Path, mimetype: str | None=None) -> None` — Attach a file from disk under its own base name; text types are read as UTF-8 text.
- `def message() -> MIMEMessage` — Build the MIME message: body, alternatives, attachments, then the headers.
- `async def send(fail_silently: bool=False) -> int` — Send through the message's backend; a message without recipients is not sent.

## `EmailMultiAlternatives`

class · defined in `oldman.mail.message`

```python
class EmailMultiAlternatives(EmailMessage)
```

A text message with alternative renderings, typically an HTML version.

Constructor:

```python
EmailMultiAlternatives(*args: Any, alternatives: Sequence[tuple[str, str]] | None=None, **kwargs: Any) -> None
```

Members:

- `def attach_alternative(content: str, mimetype: str) -> None` — Add an alternative body, for example the HTML rendering as `text/html`.

## `get_connection`

function · defined in `oldman.mail`

```python
def get_connection(backend: str | None=None, fail_silently: bool=False, **options: Any) -> BaseEmailBackend
```

Instantiate a backend: the configured one, or `backend` given as a dotted path.

## `mail_admins`

function · defined in `oldman.mail`

```python
async def mail_admins(subject: str, message: str, *, fail_silently: bool=False, connection: BaseEmailBackend | None=None, html_message: str | None=None) -> int
```

Send to `mail.admins` with `mail.subject_prefix` in front of the subject; nothing when the list is empty.

## `mail_config`

function · defined in `oldman.mail.config`

```python
def mail_config() -> MailConfig
```

Return the mail settings: an active override first, then the bootstrapped process settings.

## `MailConfigurationError`

class · defined in `oldman.mail.exceptions`

```python
class MailConfigurationError(MailError)
```

A backend path or its options cannot be used.

## `MailError`

class · defined in `oldman.mail.exceptions`

```python
class MailError(Exception)
```

Base class for outgoing mail errors.

## `outbox`

value · defined in `oldman.mail`

```python
outbox: list[EmailMessage] = []
```

## `render_mail`

function · defined in `oldman.mail.templated`

```python
async def render_mail(template_base: str, context: Mapping[str, Any] | None=None, *, language: str | None=None, environment: Environment | None=None, owner: Any=None) -> RenderedMail
```

Render the three templates behind `template_base`; the `.html` one is optional.

## `RenderedMail`

class · defined in `oldman.mail.templated`

```python
class RenderedMail
```

Subject, plain-text body and optional HTML body produced from one template base name.

Members:

- `subject: str`
- `body: str`
- `html: str | None = None`

## `send_mail`

function · defined in `oldman.mail`

```python
async def send_mail(subject: str, message: str, from_email: str | None, recipient_list: Sequence[str], *, fail_silently: bool=False, connection: BaseEmailBackend | None=None, html_message: str | None=None) -> int
```

Send one message to `recipient_list`; `html_message` adds an HTML alternative. Returns the sent count.

## `send_mass_mail`

function · defined in `oldman.mail`

```python
async def send_mass_mail(datatuple: Sequence[tuple[str, str, str | None, Sequence[str]]], *, fail_silently: bool=False, connection: BaseEmailBackend | None=None) -> int
```

Send several `(subject, message, from_email, recipient_list)` messages over one connection.

## `send_templated_mail`

function · defined in `oldman.mail.templated`

```python
async def send_templated_mail(template_base: str, context: Mapping[str, Any] | None=None, *, to: Sequence[str], from_email: str | None=None, cc: Sequence[str] | None=None, bcc: Sequence[str] | None=None, reply_to: Sequence[str] | None=None, headers: Mapping[str, str] | None=None, attachments: Sequence[Attachment] | None=None, language: str | None=None, fail_silently: bool=False, connection: BaseEmailBackend | None=None, environment: Environment | None=None, owner: Any=None) -> int
```

Render `template_base` for `to` and send it; the HTML template, when present, rides along as an alternative.

## `use_mail_config`

function · defined in `oldman.mail.config`

```python
def use_mail_config(config: MailConfig) -> Iterator[None]
```

Bind mail settings for the enclosed block (tests, one-off scripts) without process bootstrap.

## Module `oldman.mail.config`

Resolve the active mail settings, with an override for tests and scripts.

Import with `from oldman.mail.config import <name>`.

### `import_backend`

function · defined in `oldman.mail.config`

```python
def import_backend(path: str) -> type[BaseEmailBackend]
```

Import one backend class from its dotted path and check it is a mail backend.

## Module `oldman.mail.message`

Outgoing message objects modelled on django.core.mail, built on the stdlib email package.

Import with `from oldman.mail.message import <name>`.

### `envelope_address`

function · defined in `oldman.mail.message`

```python
def envelope_address(value: str) -> str
```

Bare address for the SMTP envelope, from either `addr` or `Name <addr>`.
