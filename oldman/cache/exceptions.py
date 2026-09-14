"""
@author:alex
@date:2025/10/14
@time:07:11
"""

__author__ = "alex"


class CacheIdentificationInferenceError(Exception):
    """Report failure to infer an identifier in legacy Cache code."""

    def __init__(self, message: str = "Could not infer id for resource being cached.") -> None:
        """Initialize the exception with its default inference message."""
        self.message = message
        super().__init__(self.message)


class InvalidRequestError(Exception):
    """Report an invalid request-method and Cache-option combination."""

    def __init__(self, message: str = "Type of request not supported.") -> None:
        """Initialize the exception with its default request message."""
        self.message = message
        super().__init__(self.message)


class MissingClientError(Exception):
    """Report a Cache operation attempted without a client."""

    def __init__(self, message: str = "Client is None.") -> None:
        """Initialize the exception with its default client message."""
        self.message = message
        super().__init__(self.message)
