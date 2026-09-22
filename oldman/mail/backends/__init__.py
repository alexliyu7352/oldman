"""Built-in outgoing mail backends."""

from oldman.mail.backends.base import BaseEmailBackend
from oldman.mail.backends.console import ConsoleEmailBackend
from oldman.mail.backends.dummy import DummyEmailBackend
from oldman.mail.backends.filebased import FileEmailBackend
from oldman.mail.backends.locmem import LocmemEmailBackend
from oldman.mail.backends.smtp import SMTPEmailBackend

__all__ = [
    "BaseEmailBackend",
    "ConsoleEmailBackend",
    "DummyEmailBackend",
    "FileEmailBackend",
    "LocmemEmailBackend",
    "SMTPEmailBackend",
]
