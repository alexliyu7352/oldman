"""Numbered menus that run the program's own async actions, with nested and loaded submenus."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from oldman.cli.tui.inputs import Cancelled, _interactive, _not_interactive, _read
from oldman.cli.tui.output import error, info, rule, warning
from oldman.i18n import gettext
from oldman.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Item:
    """One menu entry. Give exactly one of `action` (awaited when chosen), `submenu`, or `load`
    (awaited to build the submenu when chosen, for menus that come from elsewhere)."""

    label: object
    action: Callable[[], Awaitable[object]] | None = None
    submenu: Menu | None = None
    load: Callable[[], Awaitable[Menu]] | None = None

    def __post_init__(self) -> None:
        given = [name for name in ("action", "submenu", "load") if getattr(self, name) is not None]
        if len(given) != 1:
            raise ValueError(f"menu item {self.label!s} needs exactly one of action, submenu or load; got {given or 'none'}")


@dataclass(frozen=True, slots=True)
class Menu:
    title: object
    items: Sequence[Item]

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError(f"menu {self.title!s} has no items")


class _Finished(Exception):
    """An action ran with `after_action="exit"`: leave every menu level."""


async def run_menu(
    menu: Menu,
    *,
    after_action: Literal["return", "exit"] = "return",
    back_label: object | None = None,
    quit_label: object | None = None,
) -> None:
    """Show `menu` until the person leaves it.

    Entry `0` leaves: "Quit" on the top menu, "Back" in a submenu (`quit_label` / `back_label`
    replace the words). Ctrl-C or the end of input at a menu does the same. With
    `after_action="exit"` the menus end after one action has run; with `"return"` the menu
    comes back. An action or a `load` that raises shows the error and returns to the menu it was
    chosen from; `Cancelled` raised inside an action or a `load` just returns there. The traceback of such an
    error is logged at DEBUG, so debug mode shows it.
    """
    if not _interactive():
        raise _not_interactive(str(menu.title))
    try:
        await _run_level(
            menu, after_action=after_action, leave_label=quit_label if quit_label is not None else gettext("Quit"), back_label=back_label
        )
    except _Finished:
        return


async def _run_level(menu: Menu, *, after_action: str, leave_label: object, back_label: object | None) -> None:
    back = back_label if back_label is not None else gettext("Back")
    while True:
        rule(menu.title)
        for number, item in enumerate(menu.items, start=1):
            info(f"{number:>2}. {item.label}")
        info(f" 0. {leave_label}")
        try:
            answer = _read(": ").strip()
        except Cancelled:
            return
        if answer == "0":
            return
        chosen = _chosen(answer, menu.items)
        if chosen is None:
            warning(gettext("Enter a number from 0 to %(count)d.", count=len(menu.items)))
            continue

        if chosen.submenu is not None or chosen.load is not None:
            submenu = chosen.submenu
            if chosen.load is not None:
                try:
                    submenu = await chosen.load()
                except Cancelled:
                    continue
                except Exception as problem:  # noqa: BLE001 - shown, then back to this menu
                    _report(chosen, problem)
                    continue
            assert submenu is not None
            await _run_level(submenu, after_action=after_action, leave_label=back, back_label=back_label)
            continue

        assert chosen.action is not None
        try:
            await chosen.action()
        except Cancelled:
            continue
        except Exception as problem:  # noqa: BLE001 - shown, then back to this menu
            _report(chosen, problem)
            continue
        if after_action == "exit":
            raise _Finished


def _report(item: Item, problem: Exception) -> None:
    # One line on the menu screen. The traceback goes to the log at DEBUG: the command's console
    # log shares the screen, so it shows only when logging is at DEBUG (logging.level, or
    # core.debug while logging.level is unset).
    logger.debug("Menu item %s failed", item.label, exc_info=problem)
    error(str(problem) or type(problem).__name__)


def _chosen(answer: str, items: Sequence[Item]) -> Item | None:
    # An entry's own label comes before the numbers, as in `choose`.
    folded = answer.casefold()
    labelled = next((item for item in items if str(item.label).casefold() == folded), None)
    if labelled is not None:
        return labelled
    if answer.isdigit() and 1 <= int(answer) <= len(items):
        return items[int(answer) - 1]
    return None


__all__ = ["Item", "Menu", "run_menu"]
