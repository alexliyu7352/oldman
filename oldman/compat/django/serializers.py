"""
@author:alex
@date:2025/8/10
@time:02:35
"""

__author__ = "alex"

import pickle
from typing import Any


class RedisSerializer:
    """Match Django's built-in Redis codec; only read trusted pickle data."""

    def __init__(self, protocol=None) -> None:
        """Use the running Python's pickle protocol unless explicitly selected."""
        self.protocol = pickle.HIGHEST_PROTOCOL if protocol is None else protocol

    def dumps(self, obj: Any) -> Any:
        """Keep exact integers incrementable, but pickle bool and other values."""
        if type(obj) is int:
            return obj
        return pickle.dumps(obj, self.protocol)

    def loads(self, data: Any) -> Any:
        """Decode integers or pickle, exposing corrupt cache data as an error."""
        try:
            return int(data)
        except (ValueError, TypeError):
            return pickle.loads(data)


django_serializer = RedisSerializer()
