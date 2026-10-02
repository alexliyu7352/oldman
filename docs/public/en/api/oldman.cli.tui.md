# `oldman.cli.tui`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Terminal interaction for Oldman commands and ops tools.

Import with `from oldman.cli.tui import <name>`.

## `ANSWER_ENV_PREFIX`

value · defined in `oldman.cli.tui.inputs`

```python
ANSWER_ENV_PREFIX = 'OLDMAN_ANSWER_'
```

`OLDMAN_ANSWER_<KEY>` answers the question with that key without asking, as a preseed.

## `answer_variable`

function · defined in `oldman.cli.tui.inputs`

```python
def answer_variable(key: str) -> str
```

The environment variable that presets the answer to the question with `key`.

## `ask`

function · defined in `oldman.cli.tui.inputs`

```python
def ask(label: object, *, default: Any=None, type: Callable[[str], Any]=str, choices: Sequence[Any] | None=None, validate: Callable[[Any], object] | None=None, required: bool=True, secret: bool=False, confirm_secret: bool=False, help: object | None=None, key: str | None=None) -> Any
```

Ask for one value.

## `ask_form`

function · defined in `oldman.cli.tui.forms`

```python
def ask_form(fields: Sequence[Field], *, key_prefix: str | None=None, remember: str | os.PathLike[str] | None=None) -> dict[str, Any]
```

Ask every field in order and return `{key: value}`.

## `Cancelled`

class · defined in `oldman.cli.tui.inputs`

```python
class Cancelled(Exception)
```

The person stopped answering.

Constructor:

```python
Cancelled(reason: Literal['interrupt', 'end-of-input']) -> None
```

## `choose`

function · defined in `oldman.cli.tui.inputs`

```python
def choose(label: object, options: Iterable[Any], *, default: Any=None, match: Callable[[str], Any] | None=None, invalid: object | None=None, validate: Callable[[Any], object] | None=None, key: str | None=None) -> Any
```

Ask for one of `options`, listed with numbers.

## `choose_many`

function · defined in `oldman.cli.tui.inputs`

```python
def choose_many(label: object, options: Iterable[Any], *, default: Sequence[Any]=(), key: str | None=None) -> list[Any]
```

Ask for any number of `options`, matched as in `choose`, separated by commas or spaces.

## `confirm`

function · defined in `oldman.cli.tui.inputs`

```python
def confirm(label: object, *, default: bool=False, assume_yes: bool=False, help: object | None=None, key: str | None=None) -> bool
```

Ask yes or no.

## `echo`

function · defined in `oldman.cli.tui.output`

```python
def echo(message: object='') -> None
```

Write one line of data to stdout, exactly as given.

## `error`

function · defined in `oldman.cli.tui.output`

```python
def error(message: object) -> None
```

Write a line saying something failed; always to stderr.

## `Field`

class · defined in `oldman.cli.tui.forms`

```python
class Field
```

One question of a form; the parameters are those of `ask`. `type=bool` is asked with `confirm`.

Members:

- `key: str`
- `label: object`
- `default: Any = None`
- `type: Callable[[str], Any] = str`
- `choices: Sequence[Any] | None = None`
- `validate: Callable[[Any], object] | None = None`
- `required: bool = True`
- `secret: bool = False`
- `confirm_secret: bool = False`
- `help: object | None = None`

## `info`

function · defined in `oldman.cli.tui.output`

```python
def info(message: object) -> None
```

Write a line of explanation.

## `Item`

class · defined in `oldman.cli.tui.menus`

```python
class Item
```

One menu entry. Give exactly one of `action` (awaited when chosen), `submenu`, or `load`

Members:

- `label: object`
- `action: Callable[[], Awaitable[object]] | None = None`
- `submenu: Menu | None = None`
- `load: Callable[[], Awaitable[Menu]] | None = None`

## `Menu`

class · defined in `oldman.cli.tui.menus`

```python
class Menu
```

Members:

- `title: object`
- `items: Sequence[Item]`

## `NotInteractive`

class · defined in `oldman.cli.tui.inputs`

```python
class NotInteractive(ValueError)
```

A question needs an answer, but no one can be asked (stdin and the output are not both terminals) and it has no default.

## `progress`

function · defined in `oldman.cli.tui.waiting`

```python
def progress(label: object, *, total: float | None=None) -> Iterator[ProgressBar]
```

Show a progress bar while the block runs; `total=None` when the amount is not known.

## `ProgressBar`

class · defined in `oldman.cli.tui.waiting`

```python
class ProgressBar
```

What the `progress` block gets: move the bar on, or change its numbers or label.

Constructor:

```python
ProgressBar(label: str, total: float | None, bar: tuple[Progress, TaskID] | None) -> None
```

Members:

- `def advance(amount: float=1) -> None` — Count `amount` more units done.
- `def update(*, completed: float | None=None, total: float | None=None, label: object | None=None) -> None` — Set how much is done, the total, or the label.

## `rule`

function · defined in `oldman.cli.tui.output`

```python
def rule(title: object='') -> None
```

Write a horizontal line, with a title in it if one is given.

## `run_menu`

function · defined in `oldman.cli.tui.menus`

```python
async def run_menu(menu: Menu, *, after_action: Literal['return', 'exit']='return', back_label: object | None=None, quit_label: object | None=None) -> None
```

Show `menu` until the person leaves it.

## `simulate_input`

function · defined in `oldman.cli.tui.testing`

```python
def simulate_input(answers: Iterable[Answer]) -> Iterator[SimulatedTerminal]
```

Answer the questions asked inside the block, in order, and capture stdout and stderr.

## `SimulatedTerminal`

class · defined in `oldman.cli.tui.testing`

```python
class SimulatedTerminal
```

The answers still to give, and everything printed while the block ran.

Constructor:

```python
SimulatedTerminal(answers: Iterable[Answer]) -> None
```

Members:

- `property stdout: str`
- `property stderr: str`
- `property remaining: list[Answer]` — Answers no question asked for.
- `def read(prompt: str, *, secret: bool) -> str` — Print the prompt and the answer the way a terminal would show them; secrets stay hidden.

## `spinner`

function · defined in `oldman.cli.tui.waiting`

```python
def spinner(label: object) -> Iterator[None]
```

Show a spinner with `label` while the block runs; off a terminal, print `label` once.

## `success`

function · defined in `oldman.cli.tui.output`

```python
def success(message: object) -> None
```

Write a line saying something worked.

## `table`

function · defined in `oldman.cli.tui.output`

```python
def table(rows: Iterable[Sequence[object]], *, headers: Sequence[object] | None=None, title: object | None=None) -> None
```

Write a table. Cells are plain text; `None` shows as an empty cell.

## `warning`

function · defined in `oldman.cli.tui.output`

```python
def warning(message: object) -> None
```

Write a line saying something needs attention.
