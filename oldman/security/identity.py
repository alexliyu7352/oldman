"""The type a user id has wherever the framework takes one."""

from __future__ import annotations


def require_user_id(user_id: object) -> int:
    """Return ``user_id`` when it is exactly an ``int``; raise TypeError otherwise.

    User ids end up in Redis keys and token claims as text and are compared with ``==`` when
    read back, so only ``int`` itself is accepted: ``True`` is written as ``True`` yet equals
    ``1``, and an ``int`` subclass (an ``IntEnum`` member, a project's own int type) may print
    or compare differently from the number it holds. The range is not restricted.
    """
    if type(user_id) is not int:
        raise TypeError("user_id must be an int")
    return user_id
