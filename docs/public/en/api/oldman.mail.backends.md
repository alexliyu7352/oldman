# `oldman.mail.backends`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Built-in outgoing mail backends.

Import with `from oldman.mail.backends import <name>`.

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

## `ConsoleEmailBackend`

class · defined in `oldman.mail.backends.console`

```python
class ConsoleEmailBackend(BaseEmailBackend)
```

Write each message, followed by a separator line, to `stream` (stdout by default).

Constructor:

```python
ConsoleEmailBackend(*, fail_silently: bool=False, stream: TextIO | None=None, **options: Any) -> None
```

Members:

- `async def send_messages(messages: Sequence[EmailMessage]) -> int`

## `DummyEmailBackend`

class · defined in `oldman.mail.backends.dummy`

```python
class DummyEmailBackend(BaseEmailBackend)
```

Count the messages as sent without doing anything.

Members:

- `async def send_messages(messages: Sequence[EmailMessage]) -> int`

## `FileEmailBackend`

class · defined in `oldman.mail.backends.filebased`

```python
class FileEmailBackend(BaseEmailBackend)
```

Save messages as `<timestamp>-<n>.eml` under `file_path` (option or `mail.file_path`).

Constructor:

```python
FileEmailBackend(*, fail_silently: bool=False, file_path: str | Path | None=None, **options: Any) -> None
```

Members:

- `async def send_messages(messages: Sequence[EmailMessage]) -> int`

## `LocmemEmailBackend`

class · defined in `oldman.mail.backends.locmem`

```python
class LocmemEmailBackend(BaseEmailBackend)
```

Append every message to `oldman.mail.outbox` after building its MIME form.

Members:

- `async def send_messages(messages: Sequence[EmailMessage]) -> int`

## `SMTPEmailBackend`

class · defined in `oldman.mail.backends.smtp`

```python
class SMTPEmailBackend(BaseEmailBackend)
```

Send through an SMTP server; every option falls back to `mail.smtp` when not given.

Constructor:

```python
SMTPEmailBackend(*, host: str | None=None, port: int | None=None, username: str | None=None, password: str | None=None, use_tls: bool | None=None, use_ssl: bool | None=None, timeout: float | None=None, local_hostname: str | None=None, fail_silently: bool=False, **options: Any) -> None
```

Members:

- `async def open() -> bool`
- `async def close() -> None` — Say QUIT and drop the connection; a transport that already died (timeout, disconnect) is just dropped.
- `async def send_messages(messages: Sequence[EmailMessage]) -> int`
