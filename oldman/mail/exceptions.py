"""Mail layer errors."""


class MailError(Exception):
    """Base class for outgoing mail errors."""


class MailConfigurationError(MailError):
    """A backend path or its options cannot be used."""


__all__ = ["MailConfigurationError", "MailError"]
