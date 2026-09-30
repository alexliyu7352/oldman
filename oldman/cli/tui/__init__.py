"""Terminal interaction for Oldman commands and ops tools.

Output and input are plain functions: a command's `handle` calls them directly, and waiting
for the user simply blocks. See docs/public/zh/developers/tui.md.
"""

from oldman.cli.tui.forms import Field, ask_form
from oldman.cli.tui.inputs import ANSWER_ENV_PREFIX, Cancelled, NotInteractive, answer_variable, ask, choose, choose_many, confirm
from oldman.cli.tui.menus import Item, Menu, run_menu
from oldman.cli.tui.output import echo, error, info, rule, success, table, warning
from oldman.cli.tui.testing import SimulatedTerminal, simulate_input
from oldman.cli.tui.waiting import ProgressBar, progress, spinner

__all__ = [
    "ANSWER_ENV_PREFIX",
    "Cancelled",
    "Field",
    "Item",
    "Menu",
    "NotInteractive",
    "ProgressBar",
    "SimulatedTerminal",
    "answer_variable",
    "ask",
    "ask_form",
    "choose",
    "choose_many",
    "confirm",
    "echo",
    "error",
    "info",
    "progress",
    "rule",
    "run_menu",
    "simulate_input",
    "spinner",
    "success",
    "table",
    "warning",
]
