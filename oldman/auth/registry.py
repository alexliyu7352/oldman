"""Configured authentication User model resolution and contract validation."""

from __future__ import annotations

import importlib
from typing import Any, cast

from oldman.auth.base import AbstractUser
from oldman.auth.contracts import (
    UserModelContractError,
    validate_user_table_contract,
)
from oldman.auth.settings import AuthSettings


def import_user_model(path: str) -> Any:
    """Import one configured dotted User model path."""
    module_name, separator, attribute = path.rpartition(".")
    if not separator or not module_name or not attribute:
        raise ImportError(f"Invalid User model import path: {path}")
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


def validate_user_model(model: Any) -> type[AbstractUser]:
    """Require the selected mapper to inherit the fixed AbstractUser contract."""
    if not isinstance(model, type) or not issubclass(model, AbstractUser):
        raise UserModelContractError("configured User model must inherit oldman.auth.AbstractUser")
    validate_user_table_contract(model)
    return cast(type[AbstractUser], model)


def get_user_model(
    auth_settings: AuthSettings | None = None,
) -> type[AbstractUser]:
    """Resolve and validate the User model selected by the Auth configuration."""
    if auth_settings is None:
        from oldman.auth.apps import app as auth_app

        auth_settings = auth_app.settings
    return validate_user_model(import_user_model(auth_settings.user_model))


__all__ = ["get_user_model", "validate_user_model"]
