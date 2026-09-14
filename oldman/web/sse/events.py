"""Encoding primitives for the Server-Sent Events wire format."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServerSentEvent:
    """A single Server-Sent Events frame."""

    data: str | None = None
    event: str | None = None
    id: str | None = None
    retry: int | None = None
    comment: str | None = None


def encode_sse_event(event: ServerSentEvent) -> str:
    """Encode one event without permitting field or line injection."""
    if not isinstance(event, ServerSentEvent):
        raise TypeError("event must be a ServerSentEvent")
    if all(value is None for value in (event.data, event.event, event.id, event.retry, event.comment)):
        raise ValueError("an SSE event must contain at least one field")

    lines: list[str] = []
    if event.comment is not None:
        comment = _validate_text(event.comment, "comment")
        lines.extend(f": {line}\n" for line in _split_lines(comment))
    if event.event is not None:
        event_name = _validate_single_line(event.event, "event")
        lines.append(f"event: {event_name}\n")
    if event.id is not None:
        event_id = _validate_single_line(event.id, "id")
        if "\0" in event_id:
            raise ValueError("id must not contain NUL")
        lines.append(f"id: {event_id}\n")
    if event.retry is not None:
        if type(event.retry) is not int:
            raise TypeError("retry must be an integer")
        if event.retry < 0:
            raise ValueError("retry must not be negative")
        lines.append(f"retry: {event.retry}\n")
    if event.data is not None:
        data = _validate_text(event.data, "data")
        lines.extend(f"data: {line}\n" for line in _split_lines(data))
    lines.append("\n")
    return "".join(lines)


def _validate_text(value: object, field_name: str) -> str:
    """Return UTF-8-compatible text or reject the field."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{field_name} must contain valid UTF-8 text") from None
    return value


def _validate_single_line(value: object, field_name: str) -> str:
    """Return text that cannot inject another SSE field."""
    text = _validate_text(value, field_name)
    if "\r" in text or "\n" in text:
        raise ValueError(f"{field_name} must not contain line breaks")
    return text


def _split_lines(value: str) -> list[str]:
    """Normalize all supported line endings before SSE field expansion."""
    return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")


__all__ = ["ServerSentEvent", "encode_sse_event"]
