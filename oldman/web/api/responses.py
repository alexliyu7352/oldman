"""Strongly typed JSON API response models."""

from __future__ import annotations

from typing import Any

import msgspec

from oldman.i18n import LazyTranslation, TranslatableMsgspecModel
from oldman.web.api.actions import ResponseAction
from oldman.web.api.enums import ApiErrorCode


class DefaultApiResponse(TranslatableMsgspecModel, kw_only=True):
    """Business result with ordered browser actions."""

    error_code: int | ApiErrorCode = ApiErrorCode.OK
    message: str | LazyTranslation = ""
    data: dict[Any, Any] = msgspec.field(default_factory=dict)
    actions: list[ResponseAction] = msgspec.field(default_factory=list)


class DefaultApiFormResponse(DefaultApiResponse):
    """API response carrying first errors for concrete form fields."""

    errors: dict[str, str | LazyTranslation] = msgspec.field(default_factory=dict)


__all__ = ["DefaultApiFormResponse", "DefaultApiResponse"]
