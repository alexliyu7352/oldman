"""A form: several questions answered in one go, from the terminal, preset answers or last time's answers."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oldman.cli.tui.inputs import _checked, _preset, _Rejected, answer_variable, ask, confirm
from oldman.cli.tui.output import warning
from oldman.i18n import gettext
from oldman.utils.files import load_json_file, save_json_file

_JSON_NATIVE = (str, int, float, bool)


@dataclass(frozen=True, slots=True)
class Field:
    """One question of a form; the parameters are those of `ask`. `type=bool` is asked with `confirm`."""

    key: str
    label: object
    default: Any = None
    type: Callable[[str], Any] = str
    choices: Sequence[Any] | None = None
    validate: Callable[[Any], object] | None = None
    required: bool = True
    secret: bool = False
    confirm_secret: bool = False
    help: object | None = None


def _load_remembered(path: Path) -> dict[str, Any] | None:
    """Last time's answers; None when the file cannot be used, so it is neither read nor overwritten."""
    try:
        saved = load_json_file(path)
    except ValueError as error:
        warning(gettext("Ignoring the saved answers in %(path)s: %(error)s", path=path, error=str(error)))
        return None
    if saved is None:
        return {}
    if not isinstance(saved, dict):
        warning(gettext("Ignoring the saved answers in %(path)s: %(error)s", path=path, error=gettext("not a JSON object")))
        return None
    return saved


def _remembered_default(field: Field, value: Any) -> Any:
    """Last time's answer as this time's default, checked as a typed answer would be.

    It came from an earlier run, whose rules may have changed, or from a hand-edited file; one
    that no longer fits is shown once and the field's own default is offered instead. The
    field's own default is trusted, as it is without remembering.
    """
    if value == field.default:
        return value
    try:
        if field.type is bool:
            if not isinstance(value, bool):
                raise _Rejected(gettext("Answer yes or no."))
            return value
        if value == "":
            # As a default, an empty string is taken on Enter: it would skip `required`.
            if field.required:
                raise _Rejected(gettext("This value is required."))
            return value
        return _checked(str(value), type=field.type, choices=field.choices, validate=field.validate)
    except _Rejected as problem:
        warning(gettext("Ignoring the saved answer for %(label)s: %(error)s", label=str(field.label), error=problem.reason))
        return field.default


def ask_form(
    fields: Sequence[Field],
    *,
    key_prefix: str | None = None,
    remember: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Ask every field in order and return `{key: value}`.

    Each field is a question with the key `{key_prefix}.{field.key}` (or `field.key` without a
    prefix), so its answer can be preset like any question's: `add_site.port` is answered by
    `OLDMAN_ANSWER_ADD_SITE_PORT`. With `remember`, a JSON file keeps the answers: they become
    next time's defaults, once they pass the field's `type`, `choices` and `validate` again.
    Secrets, and values that are not plain JSON (str, int, float, bool), are not kept.
    """
    keys = [field.key for field in fields]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"form keys must be unique: {', '.join(duplicates)}")
    question_keys = {field.key: f"{key_prefix}.{field.key}" if key_prefix is not None else field.key for field in fields}
    for question_key in question_keys.values():
        answer_variable(question_key)  # a key that cannot name a variable fails before any question

    remember_path = Path(remember).expanduser() if remember is not None else None
    remembered = _load_remembered(remember_path) if remember_path is not None else None

    answers: dict[str, Any] = {}
    for field in fields:
        default = field.default
        # A preset answer wins over last time's, which then needs no checking.
        if remembered is not None and not field.secret and field.key in remembered and _preset(question_keys[field.key]) is None:
            default = _remembered_default(field, remembered[field.key])
        if field.type is bool:
            answers[field.key] = confirm(field.label, default=bool(default), help=field.help, key=question_keys[field.key])
            continue
        answers[field.key] = ask(
            field.label,
            default=default,
            type=field.type,
            choices=field.choices,
            validate=field.validate,
            required=field.required,
            secret=field.secret,
            confirm_secret=field.confirm_secret,
            help=field.help,
            key=question_keys[field.key],
        )

    if remember_path is not None and remembered is not None:
        kept = {field.key: answers[field.key] for field in fields if not field.secret and isinstance(answers[field.key], _JSON_NATIVE)}
        save_json_file({**remembered, **kept}, remember_path)
    return answers


__all__ = ["Field", "ask_form"]
