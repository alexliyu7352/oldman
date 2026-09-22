"""Outgoing mail contract: messages, backends and the module-level helpers."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babel.support import Translations
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

import oldman.conf as conf
from oldman import mail
from oldman.conf.schemas import MailConfig, SMTPMailConfig
from oldman.mail import (
    Attachment,
    EmailMessage,
    EmailMultiAlternatives,
    MailConfigurationError,
    RenderedMail,
    get_connection,
    mail_admins,
    render_mail,
    send_mail,
    send_mass_mail,
    send_templated_mail,
    use_mail_config,
)
from oldman.mail.backends.locmem import LocmemEmailBackend
from oldman.web.template import register_component_filters
from tests.test_admin_translation_boundaries import make_translations

LOCMEM = "oldman.mail.backends.locmem.LocmemEmailBackend"


def _config(**overrides: object) -> MailConfig:
    values: dict[str, object] = {"backend": LOCMEM, "default_from_email": "noreply@example.com"}
    values.update(overrides)
    return MailConfig.model_validate(values)


class MailMessageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._token = use_mail_config(_config())
        self._token.__enter__()
        self.addCleanup(self._token.__exit__, None, None, None)

    def test_plain_message_headers_follow_django(self) -> None:
        message = EmailMessage(
            "Hello 你好",
            "Body text",
            None,
            ["to@example.com", "Two <two@example.com>"],
            bcc=["hidden@example.com"],
            cc=["cc@example.com"],
            reply_to=["reply@example.com"],
            headers={"X-Trace": "abc"},
        )
        mime = message.message()

        self.assertEqual("Hello 你好", mime["Subject"])
        self.assertEqual("noreply@example.com", mime["From"])
        self.assertEqual("to@example.com, Two <two@example.com>", mime["To"])
        self.assertEqual("cc@example.com", mime["Cc"])
        self.assertEqual("reply@example.com", mime["Reply-To"])
        self.assertEqual("abc", mime["X-Trace"])
        self.assertIsNone(mime["Bcc"])
        self.assertIn("Date", mime)
        self.assertRegex(mime["Message-ID"], r"^<.+@.+>$")
        self.assertEqual("text/plain", mime.get_content_type())
        self.assertEqual("Body text\n", mime.get_content())
        self.assertEqual(["to@example.com", "Two <two@example.com>", "cc@example.com", "hidden@example.com"], message.recipients())

    def test_recipient_arguments_must_be_sequences(self) -> None:
        with self.assertRaisesRegex(TypeError, '"to" argument must be a list or tuple'):
            EmailMessage("s", "b", None, "to@example.com")  # type: ignore[arg-type]

    def test_explicit_headers_override_from_and_to(self) -> None:
        message = EmailMessage("s", "b", "real@example.com", ["to@example.com"], headers={"From": "Shown <shown@example.com>", "To": "list@example.com"})
        mime = message.message()

        self.assertEqual("Shown <shown@example.com>", mime["From"])
        self.assertEqual("list@example.com", mime["To"])
        self.assertEqual("real@example.com", message.from_email)

        # Subject and Cc are single-occurrence headers: an explicit one must replace, never duplicate, and
        # the key's case does not matter.
        overridden = EmailMessage("Generated", "b", "a@example.com", ["to@example.com"], cc=["orig@example.com"], headers={"subject": "Explicit", "CC": "cc@example.com", "X-Kind": "welcome"}).message()
        self.assertEqual(["Explicit"], overridden.get_all("Subject"))
        self.assertEqual(["cc@example.com"], overridden.get_all("Cc"))
        self.assertEqual("welcome", overridden["X-Kind"])

    def test_alternatives_and_attachments_build_the_expected_mime_tree(self) -> None:
        message = EmailMultiAlternatives("s", "plain", None, ["to@example.com"])
        message.attach_alternative("<p>html</p>", "text/html")
        message.attach("report.csv", "a,b\n1,2\n")
        message.attach("blob.bin", b"\x00\x01", "application/octet-stream")
        message.attach("unknown", b"data")
        mime = message.message()

        self.assertEqual("multipart/mixed", mime.get_content_type())
        parts = list(mime.iter_parts())
        self.assertEqual("multipart/alternative", parts[0].get_content_type())
        alternatives = [part.get_content_type() for part in parts[0].iter_parts()]
        self.assertEqual(["text/plain", "text/html"], alternatives)
        self.assertEqual(["text/csv", "application/octet-stream", "application/octet-stream"], [part.get_content_type() for part in parts[1:]])
        self.assertEqual(["report.csv", "blob.bin", "unknown"], [part.get_filename() for part in parts[1:]])
        self.assertEqual(b"\x00\x01", parts[2].get_payload(decode=True))

    def test_text_content_needs_a_text_mime_type(self) -> None:
        message = EmailMessage("s", "b", None, ["to@example.com"])
        with self.assertRaisesRegex(TypeError, "text content but a non-text MIME type"):
            message.attach("data.bin", "text", "application/octet-stream")

    def test_attach_file_reads_text_and_binary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            text_file = Path(directory) / "notes.txt"
            text_file.write_text("héllo", encoding="utf-8")
            binary_file = Path(directory) / "image.png"
            binary_file.write_bytes(b"\x89PNG")
            message = EmailMessage("s", "b", None, ["to@example.com"])
            message.attach_file(text_file)
            message.attach_file(binary_file)

            self.assertEqual([Attachment("notes.txt", "héllo", "text/plain"), Attachment("image.png", b"\x89PNG", "image/png")], message.attachments)
            parts = list(message.message().iter_parts())
            # set_content() terminates text with a newline, as every stdlib text part does.
            self.assertEqual("héllo\n", parts[1].get_content())


class MailBackendTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._token = use_mail_config(_config(admins=["admin@example.com"], subject_prefix="[Site] "))
        self._token.__enter__()
        self.addCleanup(self._token.__exit__, None, None, None)
        mail.outbox.clear()
        self.addCleanup(mail.outbox.clear)

    async def test_send_mail_uses_the_configured_backend_and_the_outbox(self) -> None:
        sent = await send_mail("Subject", "Body", None, ["to@example.com"], html_message="<b>Body</b>")

        self.assertEqual(1, sent)
        self.assertEqual(1, len(mail.outbox))
        message = mail.outbox[0]
        assert isinstance(message, EmailMultiAlternatives)
        self.assertEqual("noreply@example.com", message.from_email)
        self.assertEqual([("<b>Body</b>", "text/html")], message.alternatives)

    async def test_string_recipients_are_rejected_like_django(self) -> None:
        # A bare string satisfies Sequence[str]; without this guard "ada@example.com" became 15 recipients.
        with self.assertRaisesRegex(TypeError, '"to" argument must be a list or tuple'):
            await send_mail("Subject", "Body", None, "ada@example.com")  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, '"to" argument must be a list or tuple'):
            await send_mass_mail([("One", "1", None, "a@example.com")])  # type: ignore[list-item]
        self.assertEqual([], mail.outbox)

    async def test_message_without_recipients_is_not_sent(self) -> None:
        self.assertEqual(0, await send_mail("Subject", "Body", None, []))
        self.assertEqual(0, await EmailMessage("s", "b").send())
        self.assertEqual([], mail.outbox)

    async def test_send_mass_mail_and_mail_admins(self) -> None:
        count = await send_mass_mail([("One", "1", None, ["a@example.com"]), ("Two", "2", "x@example.com", ["b@example.com", "c@example.com"])])
        self.assertEqual(2, count)
        self.assertEqual(["One", "Two"], [message.subject for message in mail.outbox])
        self.assertEqual("x@example.com", mail.outbox[1].from_email)

        self.assertEqual(1, await mail_admins("Disk full", "Details"))
        self.assertEqual("[Site] Disk full", mail.outbox[-1].subject)
        self.assertEqual(["admin@example.com"], mail.outbox[-1].to)

        with use_mail_config(_config(admins=[])):
            self.assertEqual(0, await mail_admins("Ignored", "Nobody listens"))

    async def test_get_connection_accepts_a_dotted_path_and_rejects_others(self) -> None:
        self.assertIsInstance(get_connection(), LocmemEmailBackend)
        self.assertIsInstance(get_connection("oldman.mail.backends.dummy.DummyEmailBackend"), mail.BaseEmailBackend)
        for path in ("not-a-path", "oldman.mail.backends.nope.Missing", "oldman.mail.message.EmailMessage"):
            with self.subTest(path=path), self.assertRaises(MailConfigurationError):
                get_connection(path)

    async def test_console_backend_prints_each_message_with_a_separator(self) -> None:
        stream = io.StringIO()
        connection = get_connection("oldman.mail.backends.console.ConsoleEmailBackend", stream=stream)

        sent = await connection.send_messages([EmailMessage("Console", "Printed", None, ["to@example.com"]), EmailMessage("Second", "Again", None, ["to@example.com"])])

        self.assertEqual(2, sent)
        output = stream.getvalue()
        self.assertIn("Subject: Console", output)
        self.assertIn("Subject: Second", output)
        self.assertEqual(2, output.count("-" * 79))

    async def test_file_backend_writes_one_eml_per_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "outgoing"
            with use_mail_config(_config(file_path=str(target))):
                connection = get_connection("oldman.mail.backends.filebased.FileEmailBackend")
                sent = await connection.send_messages([EmailMessage("File", "Saved", None, ["to@example.com"])])

            self.assertEqual(1, sent)
            files = sorted(target.glob("*.eml"))
            self.assertEqual(1, len(files))
            self.assertIn(b"Subject: File", files[0].read_bytes())

        with self.assertRaisesRegex(MailConfigurationError, "file_path"):
            get_connection("oldman.mail.backends.filebased.FileEmailBackend")

    async def test_dummy_backend_counts_without_sending(self) -> None:
        connection = get_connection("oldman.mail.backends.dummy.DummyEmailBackend")
        self.assertEqual(2, await connection.send_messages([EmailMessage("a", "b", None, ["x@example.com"]), EmailMessage("c", "d", None, ["y@example.com"])]))
        self.assertEqual([], mail.outbox)

    async def test_fail_silently_swallows_backend_errors(self) -> None:
        class Broken(io.StringIO):
            def write(self, _value: str) -> int:
                raise OSError("stream closed")

        loud = get_connection("oldman.mail.backends.console.ConsoleEmailBackend", stream=Broken())
        with self.assertRaises(OSError):
            await loud.send_messages([EmailMessage("a", "b", None, ["x@example.com"])])
        quiet = get_connection("oldman.mail.backends.console.ConsoleEmailBackend", stream=Broken(), fail_silently=True)
        self.assertEqual(0, await quiet.send_messages([EmailMessage("a", "b", None, ["x@example.com"])]))

        # fail_silently covers the transport only: a header that cannot be serialised is the caller's bug.
        with tempfile.TemporaryDirectory() as directory, use_mail_config(_config(file_path=directory)):
            for backend in (quiet, get_connection("oldman.mail.backends.filebased.FileEmailBackend", fail_silently=True)):
                with self.subTest(backend=type(backend).__name__), self.assertRaises(ValueError):
                    await backend.send_messages([EmailMessage("a\r\nBcc: x", "b", None, ["x@example.com"])])


class TemplatedMailTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._token = use_mail_config(_config())
        self._token.__enter__()
        self.addCleanup(self._token.__exit__, None, None, None)
        mail.outbox.clear()
        self.addCleanup(mail.outbox.clear)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root / "mail").mkdir()
        (root / "mail/welcome.subject.txt").write_text("  {{ _('Welcome') }},\n {{ name }}  \n", encoding="utf-8")
        (root / "mail/welcome.txt").write_text("{{ _('Hello') }} {{ name }} <{{ name }}>\n", encoding="utf-8")
        (root / "mail/welcome.html").write_text("<p>{{ _('Hello') }} {{ name }} &lt; {{ name }}</p>\n", encoding="utf-8")
        (root / "mail/plain.subject.txt").write_text("Plain", encoding="utf-8")
        (root / "mail/plain.txt").write_text("Only text", encoding="utf-8")
        self.environment = Environment(loader=FileSystemLoader(str(root)), autoescape=select_autoescape(["html", "xml"]), enable_async=True)
        register_component_filters(self.environment)

    async def test_render_mail_folds_the_subject_and_skips_a_missing_html_template(self) -> None:
        rendered = await render_mail("mail/welcome", {"name": "A<b>"}, environment=self.environment)

        self.assertEqual("Welcome, A<b>", rendered.subject)
        # Jinja drops the single trailing newline; only the .html template autoescapes, as everywhere else.
        self.assertEqual("Hello A<b> <A<b>>", rendered.body)
        self.assertEqual("<p>Hello A&lt;b&gt; &lt; A&lt;b&gt;</p>", rendered.html)

        plain = await render_mail("mail/plain", environment=self.environment)
        self.assertEqual(RenderedMail(subject="Plain", body="Only text", html=None), plain)

    async def test_send_templated_mail_sends_text_with_the_html_alternative(self) -> None:
        sent = await send_templated_mail("mail/welcome", {"name": "Ada"}, to=["ada@example.com"], cc=["cc@example.com"], headers={"X-Kind": "welcome"}, environment=self.environment)

        self.assertEqual(1, sent)
        message = mail.outbox[0]
        assert isinstance(message, EmailMultiAlternatives)
        self.assertEqual("Welcome, Ada", message.subject)
        self.assertEqual(["ada@example.com"], message.to)
        self.assertEqual(["cc@example.com"], message.cc)
        self.assertEqual("welcome", message.extra_headers["X-Kind"])
        self.assertEqual([("<p>Hello Ada &lt; Ada</p>", "text/html")], message.alternatives)

    async def test_send_templated_mail_rejects_string_address_arguments(self) -> None:
        for name, kwargs in (("to", {"to": "ada@example.com"}), ("cc", {"to": ["ada@example.com"], "cc": "cc@example.com"}), ("bcc", {"to": ["ada@example.com"], "bcc": "b@example.com"})):
            with self.subTest(name=name), self.assertRaisesRegex(TypeError, f'"{name}" argument must be a list or tuple'):
                await send_templated_mail("mail/welcome", {"name": "Ada"}, environment=self.environment, **kwargs)  # type: ignore[arg-type]
        self.assertEqual([], mail.outbox)

    async def test_language_binds_the_recipient_catalog_while_rendering(self) -> None:
        class FakeTranslationService:
            def get_translations(self, language: str) -> Translations:
                assert language == "zh_Hans"
                return make_translations({"Welcome": "欢迎", "Hello": "你好"})

        with patch("oldman.web.i18n.translation.translation", FakeTranslationService()):
            rendered = await render_mail("mail/welcome", {"name": "Ada"}, language="zh_Hans", environment=self.environment)
            untranslated = await render_mail("mail/welcome", {"name": "Ada"}, environment=self.environment)

        self.assertEqual("欢迎, Ada", rendered.subject)
        self.assertEqual("你好 Ada <Ada>", rendered.body)
        self.assertEqual("Welcome, Ada", untranslated.subject)


class MailConfigTest(unittest.TestCase):
    def test_defaults_point_at_the_console_backend(self) -> None:
        config = MailConfig()
        self.assertEqual("oldman.mail.backends.console.ConsoleEmailBackend", config.backend)
        self.assertEqual("webmaster@localhost", config.default_from_email)
        self.assertEqual("[Oldman] ", config.subject_prefix)
        self.assertEqual(SMTPMailConfig(), config.smtp)
        self.assertEqual(25, config.smtp.port)
        self.assertEqual(10.0, config.smtp.timeout)

    def test_tls_modes_are_exclusive_and_backend_paths_are_shaped(self) -> None:
        with self.assertRaisesRegex(ValidationError, "mutually exclusive"):
            SMTPMailConfig(use_tls=True, use_ssl=True)
        with self.assertRaisesRegex(ValidationError, "dotted import path"):
            MailConfig(backend="console")

    def test_mail_config_requires_bootstrap_or_an_override(self) -> None:
        # Another test in the same process may have bootstrapped settings; hide them for this check.
        published = conf.__dict__.pop("settings", None)
        try:
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                mail.mail_config()
        finally:
            if published is not None:
                conf.__dict__["settings"] = published
        with use_mail_config(_config()):
            self.assertEqual(LOCMEM, mail.mail_config().backend)


if __name__ == "__main__":
    unittest.main()
