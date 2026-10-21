# Terminal interaction

`oldman.cli.tui` provides terminal output, waiting indicators, and questions for App commands and operations tools. These are ordinary functions called directly from `Command.handle`; you do not need to create a rich Console. Questions are synchronous: the event loop pauses while a person enters an answer. This is a command-line interface, not a public service.

```python
from oldman.cli import Command, tui


class CheckSites(Command):
    """List the sites this server serves."""

    name = "check-sites"
    help = "Show every enabled site and whether its upstream answers."

    async def handle(self) -> None:
        sites = [("example.org", "127.0.0.1:8000"), ("static.example.org", "127.0.0.1:8001")]
        with tui.spinner("Contacting upstreams"):
            states = [await probe(upstream) for _name, upstream in sites]
        tui.table(
            [(name, upstream, state) for (name, upstream), state in zip(sites, states, strict=True)],
            headers=["Site", "Upstream", "State"],
        )
        tui.success("Checked %d sites" % len(sites))
```

`probe` is the command's own business function and is omitted here.

## Output

| Function | Output destination | Appearance |
| --- | --- | --- |
| `echo(message="")` | stdout | This outputs one data line unchanged. |
| `info(message)` | stdout, or stderr in a `raw_stdout` command | This outputs one explanatory line. |
| `success(message)` | This uses the same destination as info. | The line has a `✓ ` prefix and appears green in terminals. |
| `warning(message)` | This uses the same destination as info. | The line has a `⚠ ` prefix and appears yellow in terminals. |
| `error(message)` | This always uses stderr. | The line has a `✗ ` prefix and appears red in terminals. |
| `table(rows, *, headers=None, title=None)` | This uses the same destination as `info`. | This displays a table. |
| `rule(title="")` | This uses the same destination as `info`. | This displays a separator with an optional title. |

- All content is plain text; rich markup is not parsed. Database values such as `[red]` and brackets in file paths display literally. `message` may be a string or the result of `gettext_lazy`.
- Colors appear only in terminals. Redirected or piped output is plain text. If a stream's encoding is not UTF-8, for example with a latin-1 server locale, symbols become `[ok]`, `[!]`, and `[x]`, and tables and separators use ASCII characters instead of raising encoding errors.
- `table` displays cells as strings and shows `None` as empty. A row with more cells than its headers raises `ValueError`. Wide cells wrap within their columns rather than being truncated. Outside a terminal, rich lays out at 80 columns or `$COLUMNS`, so one record may span several lines. Use `echo` for machine output that must be processed line by line.
- Each call uses the current `sys.stdout` and `sys.stderr`, allowing `contextlib.redirect_stdout` and test replacements to capture output.

## Waiting indicators

```python
with tui.spinner("Downloading the release"):
    await download(url, target)

with tui.progress("Copying files", total=len(files)) as bar:
    for path in files:
        await copy(path)
        bar.advance()
```

- Use `spinner(label)` for work of unknown duration and `progress(label, *, total=None)` for countable work. Pass `None` when `total` is unknown. The context provides a `ProgressBar` with `advance(amount=1)` and `update(*, completed=None, total=None, label=None)`.
- In terminals, rich refreshes from its own thread, so an indicator keeps animating while the block uses `await`. Calls to `print` and `echo` within the block appear above it, with tabs displayed as spaces. This affects only terminal display: nonterminal output has neither animation nor redirection. Indicators may nest, such as a `spinner` within each progress step. A `spinner` disappears on completion, whereas `progress` retains its final line.
- A stream must report a terminal through its own `isatty()` to show animation; `FORCE_COLOR` does not make it interactive. Otherwise, `spinner` prints `label` once, and `progress` prints `label` at the start and `label: completed/total` on normal completion. Exceptions in the block propagate without a completion line.
- A logging handler configured with `ext://sys.stdout` retains the original stream at initialization. Logs written while an indicator is active can overwrite its line. This affects display only.
- Content written directly to the terminal bypasses rich and may be erased by the next refresh. For example, a `sudo` password prompt may disappear while the program waits for input. Do not run potentially interactive commands, such as password-prompting `sudo` or scripts using `read`, inside waiting indicators. Print the operation with `info` first, then run it so prompts remain below that line.

## Questions

```python
from oldman.cli import Command, tui


class AddSite(Command):
    """Add one site to the web server."""

    name = "add-site"
    help = "Ask for a site and add it."

    async def handle(self, yes: bool = False) -> None:
        domain = tui.ask("Domain", help="The name visitors type, without https://.", key="add_site.domain")
        port = tui.ask("Upstream port", type=int, default=8000, validate=unprivileged, key="add_site.port")
        engine = tui.choose("Server", [("nginx", "Nginx"), ("openresty", "OpenResty")], default="nginx", key="add_site.engine")
        modules = tui.choose_many("Modules", ["gzip", "brotli", "http2"], default=["gzip"], key="add_site.modules")
        if tui.confirm("Reload %s now?" % engine, default=True, assume_yes=yes):
            await reload_server(engine, domain, port, modules)
```

`unprivileged` and `reload_server` are business functions belonging to the command. The former uses `raise ValueError("Ports below 1024 need root.")` for ports below 1024. Supplying `key` enables preset answers for these questions; see [preset answers](#preset-answers-for-unattended-use). Omit it when a question does not need unattended operation.

| Function | Return value | Purpose |
| --- | --- | --- |
| `ask(label, *, default=None, type=str, choices=None, validate=None, required=True, secret=False, confirm_secret=False, help=None, key=None)` | This returns the value converted by `type`. | This reads one text line. |
| `confirm(label, *, default=False, assume_yes=False, help=None, key=None)` | This returns `bool`. | This asks a yes-or-no question. |
| `choose(label, options, *, default=None, match=None, invalid=None, validate=None, key=None)` | This returns the selected value. | This selects one option from a numbered list. |
| `choose_many(label, options, *, default=(), key=None)` | This returns a list of selected values. | This selects any number of options. |

- For an empty answer, `ask` returns `default` if supplied, including an empty string. Without a default, `required=False` returns `None`; otherwise it shows "This value is required." and asks again. `type` converts the text to a value. A `ValueError` displays its reason and repeats the question; `int` and `float` have specific explanations. `choices` compares converted values. If `validate` raises `ValueError`, its message is shown before asking again.
- `secret=True` hides entered text, preserves leading and trailing whitespace, and hides defaults. With `confirm_secret=True`, the user enters the value twice. A mismatch repeats both entries.
- `confirm` accepts y, yes, n, no, and the current language's words for yes and no. A command with its own `--yes` can pass that flag to `assume_yes`; when true, confirmation succeeds without a question.
- Options for `choose` and `choose_many` may be ordinary values, displayed as text with Enum members showing their values, or `(value, label)` pairs. Matching is case-insensitive. Manually entered answers match the display label first, then the index, then the value, because a `(value, label)` option does not display its value. For `[(17, "alice"), (1, "carol")]`, entering `1` selects the first item, alice. Preset answers are supplied by people who know the values, so they match value first, then label, then index; see [preset answers](#preset-answers-for-unattended-use). For `["3", "1"]`, answering `1` selects `"1"` in both cases because its label is `1`. `choose_many` accepts comma-separated or space-separated answers and counts duplicates only once. `match(answer)` lets callers add parsing, such as mapping `zh` to `zh-Hans`; returning `None` means unrecognized. `invalid` replaces the "Enter a number from 1 to %(count)d." prompt. A `ValueError` from `validate` displays its message and repeats selection. `default` must be an option or the call raises `ValueError`. The `choose` prompt shows the default index (`[1]: `), while `choose_many` shows all selected default indexes (`[1,2]: `). Enter accepts them.
- Prompts and error explanations use the explanatory-output stream: normally stdout, but stderr for `raw_stdout` commands.

### Cancellation and nonterminals

- Ctrl-C or end-of-input, such as Ctrl-D or a closed pipe, raises `tui.Cancelled`. Its `reason` is `"interrupt"` or `"end-of-input"`, respectively. A single Ctrl-C also works inside `asyncio.run`, as used by App commands: tui temporarily restores Python's own Ctrl-C handling while reading, then restores the event-loop handler. App commands need no custom handling. The CLI prints "Aborted." on stderr and exits with code 1. To handle these cases differently, such as using defaults on end-of-input but exiting on Ctrl-C, catch the exception and inspect `reason`.
- Questions require both stdin and the prompt stream to be terminals. The latter is normally stdout and is stderr for `raw_stdout` commands. Other situations, including cron, CI, `< /dev/null`, pipes, captured command output, and `> out.txt`, do not read stdin. Preset answers take priority if present; see [preset answers](#preset-answers-for-unattended-use). Otherwise a question with a default uses it and prints one line as "question: default", with `secret` shown as `***`. `confirm` uses its `default`. Without either, the question raises `tui.NotInteractive`, a `ValueError` that the CLI reports as an ordinary error before exiting with code 1. If the question has a `key`, the message identifies the variable to set.
- Checking stdin alone is insufficient. Programs invoking a command often inherit terminal stdin but capture its prompts, leaving the command waiting invisibly. Therefore `./run.sh ops menu 2>&1 | tee session.log` does not ask questions. Use preset answers to retain an operation record, or record the whole terminal session with `script -c "./run.sh ops menu" session.log`. A `raw_stdout` command prompts on stderr, so redirecting data with `command > data.json` still permits questions. Initially closed stdin (`0<&-`) is noninteractive. Schema questions from `db migrate` and `makemigrations` follow the same rule and have no preset answers. Decisions requiring a person, such as first use, lost state, renaming, or deletion, fail if prompting is unavailable. If only migration scope must be selected, all pending migrations run without prompting, as before.
- Answers are not read sequentially from pipes because positional correspondence is fragile. Skipping a conditional question, changing its order, or adding one silently shifts every later answer. An open stdin with no writer may also wait forever.

### Preset answers for unattended use

Give a question a `key` to supply its answer in advance through an environment variable, following the same idea as Debian installer preseeding:

```sh
OLDMAN_ANSWER_ADD_SITE_DOMAIN=example.org OLDMAN_ANSWER_ADD_SITE_PORT=9000 ./run.sh ops add-site
```

- The variable name comes from `tui.answer_variable(key)`: `OLDMAN_ANSWER_` plus the uppercased key, with consecutive other characters collapsed to one `_`. For example, `startproject.type` becomes `OLDMAN_ANSWER_STARTPROJECT_TYPE`. Keys differing only in punctuation map to the same variable, such as `add-site.port` and `add_site.port`. Keys asked during one invocation must differ in letters or digits. A key may contain letters, digits, `.`, `_`, and `-` and must start with a letter or digit; otherwise the call raises `ValueError`.
- When a variable is set, its question does not prompt, even in a terminal. It prints only "question: answer (variable name)", with `secret` shown as `***`.
- Preset answers receive the same validation as typed input. `ask` applies `type`, `choices`, and `validate`. `confirm` accepts 1, true, yes, or y, and 0, false, no, or n. `choose` and `choose_many` match value, display label, then index, along with forms recognized by `match`; `choose` then runs `validate`. Invalid input raises `ValueError` identifying the variable rather than returning to an interactive question, because unattended runs have nobody to answer. An empty string counts as an empty answer: use the default, or fail if required without a default.
- `confirm` with `assume_yes=True` takes precedence over preset answers. An explicit command-line `--yes` is more specific than environment settings.
- Menus have no key and always require a person to select an item. Assign keys only to questions that need unattended operation. See [CLI reference](cli.md#project-level-commands) for the framework commands' `startproject`, `startapp`, and `startservice` variables.

### Testing

```python
import unittest

from apps.sites.commands import unprivileged
from oldman.cli import tui


class AddSiteQuestionsTest(unittest.TestCase):
    def test_a_privileged_port_is_asked_again(self) -> None:
        with tui.simulate_input(["example.org", "80", "8080"]) as terminal:
            domain = tui.ask("Domain")
            port = tui.ask("Upstream port", type=int, validate=unprivileged)
        self.assertEqual(("example.org", 8080), (domain, port))
        self.assertIn("Ports below 1024 need root.", terminal.stdout)
```

`apps.sites` is an illustrative App name; replace it with the module containing the command above. `simulate_input(answers)` supplies answers in order and captures stdout and stderr as `terminal.stdout` and `terminal.stderr`. The output matches a terminal: prompts are followed by answers, but `secret` values remain hidden. An answer of `KeyboardInterrupt` or `EOFError` cancels that question. Questions inside the block behave as interactive even when the test's stdin and stdout are not terminals. If answers run out while another question is asked, it raises `RuntimeError` identifying the prompt rather than waiting on the real terminal. `terminal.remaining` holds unused answers.

Preset answers take priority over those supplied by `simulate_input`, as needed for testing presets themselves. An `OLDMAN_ANSWER_*` left in a developer's shell can therefore answer a question with that key and misalign the test. Remove these variables inside a restoring context before testing. For example, use `with patch.dict(os.environ):` and remove keys beginning with `tui.ANSWER_ENV_PREFIX`; they are restored after the block. `CliRunner().invoke(..., env=...)` only adds variables, so set a variable to `None` to remove it.

## Forms and menus

A common operations tool presents a menu, then asks for a group of parameters before executing the selected action.

```python
from oldman.cli import Command, tui

SITE_FIELDS = [
    tui.Field("domain", "Domain", help="The name visitors type, without https://."),
    tui.Field("port", "Upstream port", type=int, default=8000),
    tui.Field("tls", "Enable TLS", type=bool, default=True),
    tui.Field("engine", "Server", choices=["nginx", "openresty"], default="nginx"),
]


async def add_site() -> None:
    answers = tui.ask_form(SITE_FIELDS, key_prefix="add_site", remember="~/.config/ops/add-site.json")
    with tui.spinner("Writing the site"):
        await write_site(**answers)
    tui.success("Added %s" % answers["domain"])


async def load_security_menu() -> tui.Menu:
    checks = await discover_checks()
    return tui.Menu("Security", [tui.Item(check.title, action=check.run) for check in checks])


MAIN_MENU = tui.Menu(
    "Maintenance",
    [
        tui.Item("Add a site", action=add_site),
        tui.Item("Nginx", submenu=tui.Menu("Nginx", [tui.Item("Reload", action=reload_nginx)])),
        tui.Item("Security", load=load_security_menu),
    ],
)


class Maintain(Command):
    """Open the maintenance menu."""

    name = "maintain"
    help = "Open the maintenance menu."

    async def handle(self) -> None:
        await tui.run_menu(MAIN_MENU, after_action="exit")
```

`write_site`, `discover_checks`, and `reload_nginx` are the tool's own asynchronous business functions.

### Forms

- `Field(key, label, ...)` accepts the same remaining parameters as `ask`. A `type=bool` field uses `confirm`. `ask_form(fields, *, key_prefix=None, remember=None)` asks questions in order and returns `{key: value}`. Duplicate `key` values raise `ValueError`.
- Every field is a keyed question, with key `{key_prefix}.{field-key}`, or just the field key without `key_prefix`. Therefore it accepts presets like any other question; see [preset answers](#preset-answers-for-unattended-use). In this example, `OLDMAN_ANSWER_ADD_SITE_PORT=9000` answers the port question. A field key that cannot form a valid question key raises `ValueError` before prompting.
- `remember` is a JSON file path supporting `~`. When the form completes, it saves answers as defaults for later runs, retaining unrelated keys. Before use, remembered values pass through the field's `type`, `choices`, and `validate` checks just like manual input; `type=bool` requires `true` or `false`. Rules or files may have changed. An invalid value produces one warning and uses the field's own default this time. A remembered empty string for a required field is also invalid. A field with a preset uses that answer directly without reading or validating the remembered value. `secret` fields and values outside native JSON types (str, int, float, and bool) are not saved. If the file is not a valid JSON object, one warning is shown, and the file is neither used nor overwritten.

### Menus

- `Menu(title, items)` contains `Item(label, *, action=None, submenu=None, load=None)`, which requires exactly one of its three choices. `action` is an async function awaited on selection, `submenu` is a fixed submenu, and `load` is an async function awaited on selection to generate a submenu, such as from plugins or remote listings. See [remote files](remote.md) for remote menu items. Supplying the wrong number of choices or an empty menu raises `ValueError` at construction.
- `await run_menu(menu, *, after_action="return", back_label=None, quit_label=None)` displays a titled separator and numbered items. `0` leaves the menu: "Quit" at the top level and "Back" in a submenu, replaceable through the two label parameters. Answers may use item text or an index, with text matched first. Ctrl-C or end-of-input at a menu is equivalent to selecting `0`.
- With `after_action="return"`, the menu reappears after an action. `"exit"` ends the entire menu, including its parents, after one action. If an action or `load` raises an exception, its message appears on stderr and control returns to the menu where it was selected. The traceback is logged at DEBUG by `oldman.cli.tui.menus`. At DEBUG, it appears both on screen and in the log file; normally only the one-line message is visible. `logging.level` controls the level and follows `core.debug` when unset. A `Cancelled` raised within an action or `load`, for example by Ctrl-C in a form, returns directly to the menu without being treated as an error.
- Menus require interaction. If the rules above prohibit questions, they raise `NotInteractive`. Provide a separate command with arguments for unattended execution, calling the same business functions.

## raw_stdout commands

A command with `raw_stdout = True` reserves stdout for data; see [CLI reference](cli.md#command-lifecycle). In `raw_stdout` commands, every tui output except `echo` moves to stderr, including explanations, status lines, tables, separators, and waiting indicators. Indicators capture only stderr while active, leaving data written to stdout untouched.

```python
import json

from oldman.cli import Command, tui


class DumpSites(Command):
    """Print every site as JSON for another program."""

    name = "dump-sites"
    help = "Print the enabled sites as JSON."
    raw_stdout = True

    async def handle(self) -> None:
        with tui.spinner("Reading the site list"):
            sites = await read_sites()
        tui.echo(json.dumps(sites))
        tui.info("Printed %d sites" % len(sites))
```

`read_sites` is another business function owned by the command. `./run.sh ops dump-sites > sites.json` produces a file containing only JSON; "Reading the site list" and "Printed …" remain in the terminal.

<!-- source: zh/developers/tui.md @ 8c13fdcf -->
