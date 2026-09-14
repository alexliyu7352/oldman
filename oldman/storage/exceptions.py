from __future__ import annotations


class StorageError(Exception):
    """Base exception for storage operations."""


class InvalidStorageName(StorageError):
    """Raised when a storage name is not a safe relative POSIX path."""


class StorageFileNotFound(StorageError):
    """Raised when a requested stored file does not exist."""


class StorageConfigurationError(StorageError):
    """Raised when a storage instance has incompatible configuration."""


class StorageAliasNotConfigured(StorageError):
    """Raised when an operation requires a storage alias that is absent."""


class StorageBackendError(StorageError):
    """Raised when a storage backend fails unexpectedly."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        name: str | None,
        alias: str | None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.name = name
        self.alias = alias
