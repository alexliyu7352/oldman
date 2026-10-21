# Terminal interaction

`oldman.cli.tui` provides terminal output, waiting indicators, and questions for App commands/operations tools. These are ordinary functions called directly in Command.handle, without creating a rich Console. Questions are synchronous: the event loop pauses while awaiting input because this is a command-line tool, not a public service.

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

probe is the command's own business function, omitted here.

## Output

| Function | Destination | Appearance |
| --- | --- | --- |
| `echo(message="")` | stdout | One unchanged data line |
| `info(message)` | stdout; stderr for raw_stdout commands | One explanatory line |
| `success(message)` | As above | `✓ ` prefix, green in terminals |
| `warning(message)` | As above | `⚠ ` prefix, yellow in terminals |
| `error(message)` | Always stderr | `✗ ` prefix, red in terminals |
| `table(rows, *, headers=None, title=None)` | Same as info | Table |
| `rule(title="")` | Same as info | Separator, optionally titled |

- Everything is plain text without rich markup parsing: database `[red]` strings and bracketed paths display literally. message accepts strings or gettext_lazy results.
- Colors appear only in terminals; redirects/pipes receive plain text. With non-UTF-8 streams such as latin-1 server locales, symbols become [ok], [!], and [x], and tables/rules use ASCII rather than raising encoding errors.
- Table cells display as strings, with None empty. Rows with more cells than headers raise ValueError. Wide cells wrap rather than truncate. Outside terminals, rich lays out at 80 columns or $COLUMNS, so one record may occupy several lines. Use echo for line-oriented machine output.
- Each call uses current sys.stdout/sys.stderr, so contextlib.redirect_stdout and test replacements capture it.

## Waiting indicators

```python
with tui.spinner("Downloading the release"):
    await download(url, target)

with tui.progress("Copying files", total=len(files)) as bar:
    for path in files:
        await copy(path)
        bar.advance()
```

- spinner(label) suits work of unknown duration; progress(label, *, total=None) suits countable work, with None for unknown totals. Its ProgressBar exposes advance(amount=1) and update(*, completed=None, total=None, label=None).
- In terminals, rich refreshes on its own thread, so indicators animate while the block awaits. It redirects print/echo above the indicator, displaying tabs as spaces. This affects terminal display only; nonterminal output has neither animation nor redirection. Indicators can nest, such as spinner within progress steps. spinner disappears on exit; progress retains its final line.
- A stream not itself a terminal by isatty() has no animation, even with FORCE_COLOR. spinner prints label once; progress prints label at start and `label: completed/total` on normal completion. Block exceptions propagate without a completion line.
- Logging handlers configured with ext://sys.stdout retain their original stream at startup. Logging during indicators can overwrite the indicator line; only display is affected.
- Direct terminal writes bypass rich and can be erased at the next refresh, such as sudo password prompts: the prompt disappears while the process still waits. Do not run potentially interactive commands (sudo/read) inside indicators. Print the operation with info first and run it below, where prompts remain visible.

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

unprivileged and reload_server are command-owned business functions. The former raises ValueError("Ports below 1024 need root.") for ports below 1024. key enables [Terminal interaction](#preset-answers-for-unattended-use); omit it when unattended operation is unnecessary.

| Function | Return value | Purpose |
| --- | --- | --- |
| `ask(label, *, default=None, type=str, choices=None, validate=None, required=True, secret=False, confirm_secret=False, help=None, key=None)` | Value converted by type | Reads one text line |
| `confirm(label, *, default=False, assume_yes=False, help=None, key=None)` | bool | Yes/no |
| `choose(label, options, *, default=None, match=None, invalid=None, validate=None, key=None)` | Selected value | Chooses one numbered option |
| `choose_many(label, options, *, default=(), key=None)` | List of selected values | Chooses any number |

- Empty ask input returns an explicit default, including an empty string. Without a default, required=False returns None; otherwise it displays "This value is required." and asks again. type converts text; ValueError explains failure and reprompts (int/float have specific explanations). choices compares converted values; validate ValueError displays its message and asks again.
- secret=True hides input without trimming whitespace and hides defaults. confirm_secret=True asks twice; mismatches restart both entries.
- confirm accepts y/yes/n/no and localized yes/no. Commands with their own --yes can pass it as assume_yes to accept without prompting.
- choose/choose_many accept plain values (displayed as text; Enum members show their values) or (value, label) pairs. Matching is case-insensitive. Manual answers match visible label first, then index, then value because paired values are hidden. For [(17, "alice"), (1, "carol")], manual 1 selects alice. [Terminal interaction](#preset-answers-for-unattended-use), supplied by people who know values, match value, label, then index. With ["3", "1"], answer 1 selects "1" in both cases because its label is 1. choose_many accepts comma/space-separated answers and deduplicates. match(answer) adds custom parsing, such as zh to zh-Hans; None means unrecognized. invalid replaces the numbered-range prompt. validate ValueError shows its message and reprompts. default must be an option or calls raise ValueError. choose displays the default index ([1]: ); choose_many displays all default indexes ([1,2]: ); Enter selects them.
- Prompts/errors use the explanatory-output stream: normally stdout, stderr for raw_stdout commands.

### Cancellation and nonterminals

- Ctrl-C or end-of-input (Ctrl-D/closed pipe) raises tui.Cancelled with reason "interrupt" or "end-of-input". One Ctrl-C also works inside asyncio.run, as used by App commands: tui temporarily restores Python's own handler during reads, then restores the event-loop handler. App commands need no handling; CLI writes "Aborted." to stderr and exits 1. Catch/check reason for different behavior, such as defaults at EOF but exit on Ctrl-C.
- Questions require both stdin and the prompt stream (normally stdout, stderr for raw_stdout) to be terminals. Otherwise, including cron, CI, redirected input/output, pipes, or subprocess capture, stdin is not read. Use [Terminal interaction](#preset-answers-for-unattended-use) first; otherwise defaults apply and print question: default (secrets as ***), and confirm uses its default. Without either, tui.NotInteractive (a ValueError) is reported as an ordinary CLI error with exit 1, identifying the environment variable when a key exists.
- Checking stdin alone is insufficient: subprocesses often inherit terminal stdin while capturing prompts, leaving invisible questions waiting. Thus ./run.sh ops menu 2>&1 | tee session.log does not prompt. Use preset answers or script -c "./run.sh ops menu" session.log to record a terminal session. raw_stdout prompts use stderr, so command > data.json still permits questions. Initially closed stdin (0<&-) is noninteractive. db migrate/makemigrations schema questions follow the same rule without preset answers: first use, lost state, rename, and deletion fail when human decisions cannot be requested. Merely selecting scope for pending migrations instead applies all pending migrations without prompting, as before.
- Answers are not read line-by-line from pipes because positional correspondence is fragile. Conditional skips, reorderings, or new questions silently misalign later answers; an open unwritten stdin may also hang forever.

### Preset answers for unattended use

A question key enables advance answers through environment variables, similar to Debian installer preseeding:

```sh
OLDMAN_ANSWER_ADD_SITE_DOMAIN=example.org OLDMAN_ANSWER_ADD_SITE_PORT=9000 ./run.sh ops add-site
```

- tui.answer_variable(key) produces OLDMAN_ANSWER_ plus uppercased key, collapsing runs of other characters into _. For example, startproject.type becomes OLDMAN_ANSWER_STARTPROJECT_TYPE. Keys differing only in punctuation collide (add-site.port and add_site.port); keys used in one run must differ in letters/digits. Keys permit only letters, digits, ., _, and -, beginning with a letter/digit; invalid keys raise ValueError.
- A supplied variable suppresses prompting even in terminals, printing question: answer (variable-name), with secrets shown as ***.
- Presets undergo the same checks as typed answers: ask uses type/choices/validate; confirm accepts 1/true/yes/y and 0/false/no/n; choose/choose_many match value, label, then index (plus match forms), and choose runs validate. Invalid input raises ValueError naming the variable rather than reprompting unattended users. Empty strings count as empty answers: use defaults, or fail when required without one.
- confirm assume_yes=True outranks presets because explicit command-line --yes is more specific than environment settings.
- Menus have no keys and always require manual selection. Give keys only to questions needing unattended operation. See [CLI reference](cli.md#project-level-commands) for framework startproject/startapp/startservice variables.

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

apps.sites is an illustrative App name; substitute your command module. simulate_input(answers) supplies ordered answers and captures stdout/stderr inside the block as terminal.stdout/terminal.stderr, matching visible prompts followed by answers without secret values. KeyboardInterrupt/EOFError answers cancel that question. Every question behaves as interactive even with nonterminal test streams. Exhausted answers raise RuntimeError naming the prompt rather than waiting on a real terminal. terminal.remaining contains unused answers.

Presets outrank simulate_input answers intentionally, enabling preset tests. A developer-shell OLDMAN_ANSWER_* can therefore answer a same-key question and misalign test input. Remove such variables within a restoring context before testing, for example patch.dict(os.environ) with keys beginning tui.ANSWER_ENV_PREFIX deleted. CliRunner().invoke(..., env=...) adds variables; set values to None to remove them.

## Forms and menus

A common operations-tool pattern is a menu whose chosen action gathers parameters before executing.

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

write_site, discover_checks, and reload_nginx are tool-owned asynchronous business functions.

### Forms

- Field(key, label, ...) takes the same remaining parameters as ask. type=bool uses confirm. ask_form(fields, *, key_prefix=None, remember=None) asks in order and returns {key: value}; duplicate keys raise ValueError.
- Each field has a question key `{key_prefix}.{field-key}`, or just field-key without a prefix, enabling [Terminal interaction](#preset-answers-for-unattended-use). In the example, OLDMAN_ANSWER_ADD_SITE_PORT=9000 supplies the port. Invalid combined question keys raise ValueError before prompting.
- remember is a JSON file path supporting ~. Completed answers are saved as future defaults while unrelated keys remain. Remembered answers first pass the same type/choices/validate checks as manual input (type=bool requires true/false): rules or files may have changed. Invalid values warn once and use the field's own default; remembered empty strings for required fields are invalid too. Presets bypass reading/validating remembered answers. Secrets and values outside native JSON str/int/float/bool types are not written. Invalid JSON objects warn once, are unused this time, and are not overwritten.

### Menus

- Menu(title, items) contains Item(label, *, action=None, submenu=None, load=None), requiring exactly one: action is an awaited async function; submenu a fixed Menu; load an async submenu factory awaited on selection for plugin/remote content. See [Remote files](remote.md) for remote files. Wrong counts or empty menus raise ValueError during construction.
- await run_menu(menu, *, after_action="return", back_label=None, quit_label=None) shows a title rule and numbered items. 0 leaves: "Quit" at root, "Back" in submenus, customizable through those labels. Answers match labels before indexes. Ctrl-C/EOF at menus acts as 0.
- after_action="return" returns to the menu after actions; "exit" ends the entire menu, including parents. Action/load exceptions show their messages on stderr and return to the selecting menu. Tracebacks log at DEBUG under oldman.cli.tui.menus: DEBUG displays them in terminal/files; ordinarily only the message appears. logging.level controls this, falling back to core.debug when unset. Cancelled inside action/load, such as form Ctrl-C, returns to the menu without error.
- Menus require interaction and raise NotInteractive under the rules above. For unattended use, create an argument-based command calling the same business functions.

## raw_stdout commands

raw_stdout=True reserves stdout for data (see [CLI reference](cli.md#command-lifecycle)). Apart from echo, all tui explanatory text, status, tables, rules, and indicators move to stderr. Waiting indicators capture only stderr, leaving stdout data untouched.

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

read_sites is another command-owned business function. ./run.sh ops dump-sites > sites.json writes JSON only; "Reading the site list" and "Printed …" remain in the terminal.

<!-- source: zh/developers/tui.md @ 8c13fdcf -->
