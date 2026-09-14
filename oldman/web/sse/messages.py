"""Strongly typed Redis envelope for distributed browser events."""

from __future__ import annotations

from enum import StrEnum

from oldman.serializers import MsgspecModel


class SSETargetType(StrEnum):
    """Supported routing targets for one distributed browser event."""

    USER = "user"
    STREAM = "stream"


class SSEPublishedMessage(
    MsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec supports freezing this wire-only subclass
):
    """Versioned payload sent through the shared Redis SSE channel."""

    target_type: SSETargetType
    target: str
    event: str
    payload: bytes
    version: int = 1


class SSESessionInvalidatedPayload(MsgspecModel, kw_only=True):
    """Final translated payload sent when a guarded browser session expires."""

    title: str
    message: str
    login_url: str


__all__ = ["SSEPublishedMessage", "SSESessionInvalidatedPayload", "SSETargetType"]
