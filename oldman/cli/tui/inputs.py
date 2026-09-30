"""Questions to the person at the terminal: a line of text, yes or no, one or several choices.

Asking is synchronous: in a command's `handle` the event loop simply waits while the person types.
Prompts go where status lines go (stderr inside a `raw_stdout` command). Unless stdin and that
stream are both terminals nothing is read: a question with a default takes it, one without raises
`NotInteractive`.
"""

from __future__ import annotations

import getpass
import os
import re
import signal
import sys
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any, Literal, Protocol, TextIO

from oldman.cli.tui.output import _descriptions_stream, _is_terminal, info, warning
from oldman.i18n import gettext


class Cancelled(Exception):
    """The person stopped answering.

    `reason` is `"interrupt"` for Ctrl-C and `"end-of-input"` when input ended (Ctrl-D, a closed
    pipe), so a caller can treat them differently.
    """

    def __init__(self, reason: Literal["interrupt", "end-of-input"]) -> None:
        super().__init__(reason)
        self.reason = reason


class NotInteractive(ValueError):
    """A question needs an answer, but no one can be asked (stdin and the output are not both terminals) and it has no default."""


class _Reader(Protocol):
    def read(self, prompt: str, *, secret: bool) -> str: ...


#: Set by `simulate_input`: answers come from it instead of the terminal.
_reader: ContextVar[_Reader | None] = ContextVar("oldman_cli_tui_reader", default=None)


def _interactive() -> bool:
    """Whether a person can see and answer questions: `simulate_input` is active, or stdin and the
    stream the questions are written to are both terminals.

    stdin alone is not enough: a program that runs the command and captures its output, or
    `command > out.txt`, would get the questions while the command waited on the terminal for an
    answer nobody knows is wanted. `command 2>&1 | tee log` is refused for the same reason.
    """
    if _reader.get() is not None:
        return True
    return _is_terminal(sys.stdin) and _is_terminal(_descriptions_stream())


@contextmanager
def _ctrl_c_interrupts_reading() -> Iterator[None]:
    """Let Ctrl-C interrupt a blocking read even inside `asyncio.run`.

    The runner turns the first Ctrl-C into cancelling its main task. A blocking read never
    notices: the prompt stays, and the cancellation lands at the next await. While reading, the
    event loop is not running anyway, so SIGINT gets Python's own handler back and raises
    KeyboardInterrupt in the read. Only the main thread can swap handlers; a process that ignores
    SIGINT keeps ignoring it.
    """
    previous = signal.getsignal(signal.SIGINT)
    if threading.current_thread() is not threading.main_thread() or previous in (None, signal.SIG_IGN, signal.default_int_handler):
        yield
        return
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def _read(prompt: str, *, secret: bool = False) -> str:
    simulated = _reader.get()
    if simulated is not None:
        return simulated.read(prompt, secret=secret)
    stream = _descriptions_stream()
    try:
        with _ctrl_c_interrupts_reading():
            return _read_from_terminal(prompt, stream, secret=secret)
    except KeyboardInterrupt:
        # Leave the shell prompt on a line of its own.
        stream.write("\n")
        stream.flush()
        raise Cancelled("interrupt") from None
    except EOFError:
        stream.write("\n")
        stream.flush()
        raise Cancelled("end-of-input") from None


def _read_from_terminal(prompt: str, stream: TextIO, *, secret: bool) -> str:
    if secret:
        return getpass.getpass(prompt, stream=stream)
    if stream is sys.stdout and "readline" in sys.modules:
        # readline draws the prompt on stdout itself and redraws it while the line is edited.
        return input(prompt)
    # Without readline, input() writes its prompt to stderr, which is not the stream checked to be
    # a terminal: `command 2>err.log` would hide the question in the file.
    stream.write(prompt)
    stream.flush()
    return input()


#: `OLDMAN_ANSWER_<KEY>` answers the question with that key without asking, as a preseed.
ANSWER_ENV_PREFIX = "OLDMAN_ANSWER_"
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def answer_variable(key: str) -> str:
    """The environment variable that presets the answer to the question with `key`.

    The key upper-cased, every run of other characters than letters and digits as `_`:
    `startproject.type` is answered by `OLDMAN_ANSWER_STARTPROJECT_TYPE`. Keys that differ only in
    those other characters (`add-site.port`, `add_site.port`) share one variable, so keys asked in
    the same run must differ in their letters or digits.
    """
    if not _KEY.fullmatch(key):
        raise ValueError(f"question key {key!r} must start with a letter or digit and use only letters, digits, '.', '_' and '-'")
    return ANSWER_ENV_PREFIX + re.sub(r"[^A-Za-z0-9]+", "_", key).upper()


def _preset(key: str | None) -> tuple[str, str] | None:
    """`(variable, value)` when the question's answer is preset in the environment."""
    if key is None:
        return None
    variable = answer_variable(key)
    value = os.environ.get(variable)
    return None if value is None else (variable, value)


def _not_interactive(label: str, key: str | None = None) -> NotInteractive:
    if key is None:
        return NotInteractive(gettext("%(label)s needs an answer, but stdin and the output are not both terminals.", label=label))
    return NotInteractive(gettext("%(label)s needs an answer: run it in a terminal or set %(variable)s.", label=label, variable=answer_variable(key)))


def _preset_invalid(variable: str, problem: str) -> ValueError:
    return ValueError(gettext("%(variable)s is not valid: %(error)s", variable=variable, error=problem))


class _Rejected(Exception):
    """An answer that does not fit, with the reason to show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _conversion_problem(converter: Callable[[str], Any], error: ValueError) -> str:
    if converter is int:
        return gettext("Enter a whole number.")
    if converter is float:
        return gettext("Enter a number.")
    detail = str(error)
    return gettext("Invalid value: %(detail)s", detail=detail) if detail else gettext("Invalid value.")


def _checked(
    answer: str,
    *,
    type: Callable[[str], Any],
    choices: Sequence[Any] | None,
    validate: Callable[[Any], object] | None,
) -> Any:
    """The value of a non-empty answer, or `_Rejected` saying why it does not fit."""
    try:
        value = type(answer)
    except ValueError as error:
        raise _Rejected(_conversion_problem(type, error)) from None
    if choices is not None and value not in choices:
        raise _Rejected(gettext("Choose one of: %(choices)s", choices=", ".join(str(choice) for choice in choices)))
    if validate is not None:
        try:
            validate(value)
        except ValueError as error:
            raise _Rejected(str(error) or gettext("Invalid value.")) from None
    return value


def ask(
    label: object,
    *,
    default: Any = None,
    type: Callable[[str], Any] = str,
    choices: Sequence[Any] | None = None,
    validate: Callable[[Any], object] | None = None,
    required: bool = True,
    secret: bool = False,
    confirm_secret: bool = False,
    help: object | None = None,
    key: str | None = None,
) -> Any:
    """Ask for one value.

    An empty answer gives `default` when one was given (an empty string counts), `None` when the
    question is not `required`, and otherwise asks again. `type` turns the text into the value;
    `choices` are compared with the converted value; `validate` raises `ValueError` to reject it
    with its message. A `secret` answer is neither shown nor trimmed; with `confirm_secret` it is
    typed twice.

    With `key`, the variable `answer_variable(key)` presets the answer: the question is not asked,
    and a value that does not fit raises `ValueError` naming the variable.
    """
    text = str(label)
    preset = _preset(key)
    if preset is not None:
        variable, raw = preset
        answer = raw if secret else raw.strip()
        if answer == "":
            if default is None and required:
                raise _preset_invalid(variable, gettext("This value is required."))
            value = default
        else:
            try:
                value = _checked(answer, type=type, choices=choices, validate=validate)
            except _Rejected as problem:
                raise _preset_invalid(variable, problem.reason) from None
        info(f"{text}: {'***' if secret else ('' if value is None else value)} ({variable})")
        return value
    if not _interactive():
        if default is not None:
            info(f"{text}: {'***' if secret else default}")
            return default
        if not required:
            return None
        raise _not_interactive(text, key)
    if help is not None:
        info(help)

    shown_choices = [str(choice) for choice in choices] if choices is not None else None
    prompt = text
    if shown_choices:
        prompt += f" ({'/'.join(shown_choices)})"
    if default not in (None, "") and not secret:
        prompt += f" [{default}]"
    prompt += ": "

    while True:
        raw = _read(prompt, secret=secret)
        answer = raw if secret else raw.strip()
        if answer == "":
            if default is not None:
                return default
            if not required:
                return None
            warning(gettext("This value is required."))
            continue
        try:
            value = _checked(answer, type=type, choices=choices, validate=validate)
        except _Rejected as problem:
            warning(problem.reason)
            continue
        if secret and confirm_secret and _read(gettext("Confirm %(label)s", label=text) + ": ", secret=True) != raw:
            warning(gettext("The two entries do not match."))
            continue
        return value


_TRUE_WORDS = {"1", "true", "y", "yes"}
_FALSE_WORDS = {"0", "false", "n", "no"}


def confirm(
    label: object,
    *,
    default: bool = False,
    assume_yes: bool = False,
    help: object | None = None,
    key: str | None = None,
) -> bool:
    """Ask yes or no.

    `assume_yes` answers yes without asking, for a command's own `--yes`; it wins over a preset.
    With `key`, the variable `answer_variable(key)` presets the answer: 1/true/yes/y or
    0/false/no/n (and the words of the current language), empty for the default.
    """
    text = str(label)
    yes, no = gettext("yes"), gettext("no")
    yes_words = _TRUE_WORDS | {yes.lower()}
    no_words = _FALSE_WORDS | {no.lower()}
    if assume_yes:
        info(f"{text}: {yes}")
        return True
    preset = _preset(key)
    if preset is not None:
        variable, raw = preset
        answer = raw.strip().lower()
        if answer == "":
            value = default
        elif answer in yes_words | no_words:
            value = answer in yes_words
        else:
            raise ValueError(gettext("%(variable)s must be true or false, not %(value)r.", variable=variable, value=raw))
        info(f"{text}: {yes if value else no} ({variable})")
        return value
    if not _interactive():
        info(f"{text}: {yes if default else no}")
        return default
    if help is not None:
        info(help)
    prompt = f"{text} [{'Y/n' if default else 'y/N'}]: "
    while True:
        answer = _read(prompt).strip().lower()
        if answer == "":
            return default
        if answer in yes_words:
            return True
        if answer in no_words:
            return False
        warning(gettext("Answer yes or no."))


def _option_text(value: object) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)


def _options(options: Iterable[Any]) -> list[tuple[Any, str]]:
    """`(value, text)` pairs from options given as pairs or as plain values."""
    pairs = [(option[0], str(option[1])) if isinstance(option, tuple) and len(option) == 2 else (option, _option_text(option)) for option in options]
    if not pairs:
        raise ValueError("choose needs at least one option")
    return pairs


_NO_PICK = object()


def _pick(answer: str, pairs: list[tuple[Any, str]], match: Callable[[str], Any] | None, *, preset: bool) -> Any:
    """The option `answer` names, or `_NO_PICK`.

    A person types what the list shows: the text first, then the number, and the value (hidden for
    `(value, text)` options) last, so a typed 1 is the first entry even when some value is 1. A
    preset answer is written by someone who knows the values: the value first, then the text, then
    the number, so a preset 1 for options "3" and "1" is the option "1". `match` resolves the rest.
    """
    folded = answer.casefold()
    by_text = next((value for value, text in pairs if text.casefold() == folded), _NO_PICK)
    by_value = next((value for value, _text in pairs if _option_text(value).casefold() == folded), _NO_PICK)
    by_number = pairs[int(answer) - 1][0] if answer.isdigit() and 1 <= int(answer) <= len(pairs) else _NO_PICK
    for picked in (by_value, by_text, by_number) if preset else (by_text, by_number, by_value):
        if picked is not _NO_PICK:
            return picked
    if match is not None:
        matched = match(answer)
        if matched is not None and any(matched == value for value, _text in pairs):
            return matched
    return _NO_PICK


def _shown(value: Any, pairs: list[tuple[Any, str]]) -> str:
    return next(shown for option, shown in pairs if option == value)


def _options_invalid(variable: str, pairs: list[tuple[Any, str]]) -> ValueError:
    return ValueError(gettext("%(variable)s must be one of: %(choices)s", variable=variable, choices=", ".join(shown for _value, shown in pairs)))


def choose(
    label: object,
    options: Iterable[Any],
    *,
    default: Any = None,
    match: Callable[[str], Any] | None = None,
    invalid: object | None = None,
    validate: Callable[[Any], object] | None = None,
    key: str | None = None,
) -> Any:
    """Ask for one of `options`, listed with numbers.

    Options are plain values (shown as text; an Enum member by its value) or `(value, text)`
    pairs. A typed answer is matched by the text shown, then the number, then the value; a preset
    one by the value, then the text, then the number. `match` resolves anything else, such as an
    alias, to a value. `invalid` replaces the message shown for an answer that fits nothing.
    `validate` raises `ValueError` to reject a chosen value with its message, and the question is
    asked again. With `key`, the variable `answer_variable(key)` presets the answer; one that fits
    no option or fails `validate` raises `ValueError` naming the variable.
    """
    pairs = _options(options)
    if default is not None and not any(default == value for value, _text in pairs):
        raise ValueError(f"default {default!r} is not one of the options")
    text = str(label)
    preset = _preset(key)
    if preset is not None:
        variable, raw = preset
        answer = raw.strip()
        value = default if answer == "" and default is not None else _pick(answer, pairs, match, preset=True)
        if value is _NO_PICK:
            raise _options_invalid(variable, pairs)
        if validate is not None:
            try:
                validate(value)
            except ValueError as error:
                raise _preset_invalid(variable, str(error) or gettext("Invalid value.")) from None
        info(f"{text}: {_shown(value, pairs)} ({variable})")
        return value
    if not _interactive():
        if default is not None:
            info(f"{text}: {_shown(default, pairs)}")
            return default
        raise _not_interactive(text, key)

    default_number = next((number for number, (value, _text) in enumerate(pairs, start=1) if value == default), None)
    prompt = f"[{default_number}]: " if default_number is not None else ": "
    while True:
        info(text)
        for number, (_value, shown) in enumerate(pairs, start=1):
            info(f"{number}. {shown}")
        answer = _read(prompt).strip()
        if answer == "" and default is not None:
            return default
        picked = _pick(answer, pairs, match, preset=False)
        if picked is _NO_PICK:
            warning(str(invalid) if invalid is not None else gettext("Enter a number from 1 to %(count)d.", count=len(pairs)))
            continue
        if validate is not None:
            try:
                validate(picked)
            except ValueError as error:
                warning(str(error) or gettext("Invalid value."))
                continue
        return picked


def _many(answer: str, pairs: list[tuple[Any, str]], *, preset: bool) -> list[Any]:
    """The values named in an answer, in order and once each; `_Rejected` naming an item that fits none."""
    picked: list[Any] = []
    for item in answer.replace(",", " ").split():
        value = _pick(item, pairs, None, preset=preset)
        if value is _NO_PICK:
            raise _Rejected(gettext("Not in the list: %(item)s", item=item))
        if value not in picked:
            picked.append(value)
    return picked


def choose_many(label: object, options: Iterable[Any], *, default: Sequence[Any] = (), key: str | None = None) -> list[Any]:
    """Ask for any number of `options`, matched as in `choose`, separated by commas or spaces.

    With `key`, the variable `answer_variable(key)` presets the answer in the same form; empty
    means `default`.
    """
    pairs = _options(options)
    for value in default:
        if not any(value == option for option, _text in pairs):
            raise ValueError(f"default {value!r} is not one of the options")
    text = str(label)
    preset = _preset(key)
    if preset is not None:
        variable, raw = preset
        try:
            chosen = _many(raw, pairs, preset=True) if raw.strip() else list(default)
        except _Rejected:
            raise _options_invalid(variable, pairs) from None
        info(f"{text}: {', '.join(_shown(value, pairs) for value in chosen)} ({variable})")
        return chosen
    if not _interactive():
        info(f"{text}: {', '.join(shown for value, shown in pairs if value in default)}")
        return list(default)

    default_numbers = [str(number) for number, (value, _text) in enumerate(pairs, start=1) if value in default]
    prompt = f"[{','.join(default_numbers)}]: " if default_numbers else ": "
    while True:
        info(text)
        for number, (_value, shown) in enumerate(pairs, start=1):
            info(f"{number}. {shown}")
        answer = _read(prompt)
        if not answer.strip():
            return list(default)
        try:
            return _many(answer, pairs, preset=False)
        except _Rejected as problem:
            warning(problem.reason)


__all__ = ["ANSWER_ENV_PREFIX", "Cancelled", "NotInteractive", "answer_variable", "ask", "choose", "choose_many", "confirm"]
