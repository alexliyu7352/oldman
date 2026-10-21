# Mail

`oldman.mail` sends mail with an interface shaped like Django's `django.core.mail`, entirely through coroutines. Messages use the standard-library `email.message.EmailMessage`; SMTP transport uses [aiosmtplib](https://github.com/cole/aiosmtplib). It only hands one or more messages to a backend, without queuing, retrying, or receiving mail.

## Configuration

The root `mail` settings are shared by Web and task processes:

```yaml
mail:
  backend: oldman.mail.backends.smtp.SMTPEmailBackend
  default_from_email: "Oldman <noreply@example.com>"
  subject_prefix: "[Oldman] "
  admins:
    - ops@example.com
  smtp:
    host: smtp.example.com
    port: 587
    username: mailer
    password: "..."
    use_tls: true
    timeout: 10
```

| Field | Default | Meaning |
| --- | --- | --- |
| `backend` | `oldman.mail.backends.console.ConsoleEmailBackend` | Backend class import path; prints mail to stdout by default; explicitly select smtp in production |
| `default_from_email` | `webmaster@localhost` | Used when the message supplies no sender |
| `subject_prefix` | `[Oldman] ` | Prepended only to `mail_admins()` subjects, as in Django |
| `admins` | Empty | `mail_admins()` recipients; that function sends nothing when empty |
| `file_path` | Empty | Directory for `.eml` files written by the filebased backend |
| `smtp.host` / `port` | `localhost` / `25` | SMTP server |
| `smtp.username` / `password` | Empty | No authentication when empty |
| `smtp.use_tls` | `false` | Upgrades with STARTTLS after connecting, usually on port 587 |
| `smtp.use_ssl` | `false` | TLS from initial connection, usually on port 465; mutually exclusive with `use_tls` |
| `smtp.timeout` | `10` | Connection and per-command timeout in seconds |
| `smtp.local_hostname` | Empty | Hostname reported in EHLO |

Like database and Redis passwords, passwords are stored in YAML; settings reads only YAML. `settings sync` adds this section, including comments, to existing configuration files.

Built-in backends:

| Backend | Purpose |
| --- | --- |
| `oldman.mail.backends.smtp.SMTPEmailBackend` | Actual delivery; one connection per `send_messages()`, reusable across calls inside `async with` |
| `oldman.mail.backends.console.ConsoleEmailBackend` | Prints to `stream` (stdout by default), with a separator after each message; development default |
| `oldman.mail.backends.filebased.FileEmailBackend` | Writes each message as `<timestamp>-<sequence>.eml` under `mail.file_path` or the `file_path` option |
| `oldman.mail.backends.locmem.LocmemEmailBackend` | Appends to `oldman.mail.outbox` for tests |
| `oldman.mail.backends.dummy.DummyEmailBackend` | Counts only, without sending |

## Sending

```python
from oldman.mail import send_mail

await send_mail(
    "Welcome",
    "Plain text body",
    None,                      # None selects mail.default_from_email
    ["ada@example.com"],
    html_message="<p>HTML body</p>",
)
```

The return value counts messages accepted by the backend. Messages without recipients are not sent and return 0. `fail_silently=True` suppresses only backend transport errors (connection/authentication failures and rejected mail). Programming errors such as missing templates or invalid address types still propagate.

Related helpers: `send_mass_mail([(subject, body, from_email, recipients), ...])` sends multiple messages over one connection; `mail_admins(subject, body)` sends to `mail.admins` with the subject prefix added automatically.

## Message objects

```python
from oldman.mail import EmailMultiAlternatives

message = EmailMultiAlternatives(
    subject="Report",
    body="See attachment",
    from_email="Reports <reports@example.com>",
    to=["ada@example.com"],
    cc=["lead@example.com"],
    bcc=["audit@example.com"],
    reply_to=["support@example.com"],
    headers={"X-Report": "weekly"},
)
message.attach_alternative("<p>See attachment</p>", "text/html")
message.attach("report.csv", "a,b\n1,2\n", "text/csv")   # Text content requires a text/* MIME type
message.attach_file("/tmp/chart.png")                      # Guesses type from the filename; falls back to application/octet-stream
await message.send()
```

`to`, `cc`, `bcc`, and `reply_to` must be lists or tuples; strings raise `TypeError`. Bcc appears only in the SMTP envelope, not message headers. `message()` returns the standard-library `EmailMessage`, automatically adding Date and Message-ID. Same-named entries in `headers` override defaults.

`get_connection(backend=None, fail_silently=False, **options)` returns a backend directly. For batch sending:

```python
from oldman.mail import get_connection

async with get_connection() as connection:
    await connection.send_messages(messages)
```

## Template mail

Django has no built-in equivalent of this layer, but flows such as password reset need it, so the framework provides `send_templated_mail`. It uses three templates, with the first two required:

- `<name>.subject.txt`: subject, collapsed to one line after rendering;
- `<name>.txt`: plain-text body;
- `<name>.html`: optional HTML alternative, sent when present.

```python
from oldman.mail import send_templated_mail

await send_templated_mail(
    "mail/welcome",
    {"name": user.display_name},
    to=[user.email],
    language=user.language,
)
```

Templates use the framework's Jinja environment. Matching files in the project's `templates/` override built-ins. `.txt` is unescaped and `.html` escaped, as with page templates. A `language` code binds that translation catalog during rendering, so `{{ _("...") }}` uses the recipient's language independently of the current request. This requires initialized Web i18n. `render_mail()` renders without sending and returns `RenderedMail(subject, body, html)`.

## When to send

`send_mail` is a coroutine: `await` it directly in request handling. SMTP has a timeout (10 seconds by default), and failures raise exceptions. To avoid waiting for mail in the response, use the in-process background task manager (the Web service's `task_manager`). For actual queuing/retries, wrap `send_mail` in a [Distributed Taskiq tasks](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/distributed-tasks.md) task. The mail layer does not create its own queue.

## Testing

Unit tests use the locmem backend and `use_mail_config()` without bootstrap:

```python
from oldman import mail
from oldman.conf.schemas import MailConfig
from oldman.mail import use_mail_config

with use_mail_config(MailConfig(backend="oldman.mail.backends.locmem.LocmemEmailBackend")):
    await send_mail(...)
assert mail.outbox[0].subject == "..."
```

The framework tests its SMTP backend against a local aiosmtpd server for real sending/receiving (`tests/test_oldman_mail_smtp.py`). Projects generally need not repeat those tests.

## Verifying production settings

```bash
oldman web mail sendtest ops@example.com
```

This sends a test email with that service's settings and prints the accepted-message count. The console backend prints the message itself. It corresponds to Django's `sendtestemail`.

## Adding a backend

Subclass `oldman.mail.BaseEmailBackend` and implement `send_messages(messages) -> int`. Connection-owning backends also implement `open()` (returning True when a connection is newly opened) and `close()`. Constructor arguments correspond to `get_connection(**options)`. Set the class path in `mail.backend`; no other code changes are needed.

<!-- source: zh/developers/mail.md @ 60ab2b58 -->
