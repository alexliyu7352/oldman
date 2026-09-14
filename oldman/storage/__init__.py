"""Public async storage API."""

from oldman.storage.backends import FileSystemStorage, InMemoryStorage
from oldman.storage.base import Storage, StorageContent, validate_storage_name
from oldman.storage.exceptions import (
    InvalidStorageName,
    StorageAliasNotConfigured,
    StorageBackendError,
    StorageConfigurationError,
    StorageError,
    StorageFileNotFound,
)
from oldman.storage.models import UploadTo, file_column
from oldman.storage.registry import (
    StorageProxy,
    StorageRegistry,
    default_storage,
    media_storage,
    memory_storage,
    storages,
)
from oldman.storage.streams import FileInfo, StoredFile

__all__ = (
    "FileInfo",
    "FileSystemStorage",
    "InMemoryStorage",
    "InvalidStorageName",
    "Storage",
    "StorageAliasNotConfigured",
    "StorageBackendError",
    "StorageConfigurationError",
    "StorageContent",
    "StorageError",
    "StorageFileNotFound",
    "StorageProxy",
    "StorageRegistry",
    "StoredFile",
    "UploadTo",
    "default_storage",
    "file_column",
    "media_storage",
    "memory_storage",
    "storages",
    "validate_storage_name",
)
