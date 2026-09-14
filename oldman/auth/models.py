"""Default concrete User model."""

from oldman.auth.base import AbstractUser


class User(AbstractUser):
    """Ready-to-use User model selected by the default Auth configuration."""


__all__ = ["User"]
