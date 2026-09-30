# 终端交互（tui）

`oldman.cli.tui` 给 App 命令和运维工具提供终端输出、等待提示和提问。它们都是普通函数，在 `Command.handle` 里直接调用；不需要自己建 rich Console。提问是同步的：等人输入时事件循环停住，这是命令行，不是对外服务。

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

`probe` 是命令自己的业务函数，这里省略。

## 输出

| 函数 | 写到哪里 | 样子 |
| --- | --- | --- |
| `echo(message="")` | stdout | 一行数据，原样输出 |
| `info(message)` | stdout；`raw_stdout` 命令里是 stderr | 一行说明 |
| `success(message)` | 同上 | `✓ ` 前缀，终端里是绿色 |
| `warning(message)` | 同上 | `⚠ ` 前缀，终端里是黄色 |
| `error(message)` | 总是 stderr | `✗ ` 前缀，终端里是红色 |
| `table(rows, *, headers=None, title=None)` | 同 `info` | 表格 |
| `rule(title="")` | 同 `info` | 分隔线，可带标题 |

- 所有内容按纯文本输出，不解析 rich 标记：数据库里的 `[red]`、文件路径里的方括号都原样显示。`message` 可以是字符串，也可以是 `gettext_lazy` 的结果。
- 颜色只在终端里出现；输出被重定向或管道接走时是纯文本。流的编码不是 UTF-8（例如服务器 locale 是 latin-1）时，符号换成 `[ok]`、`[!]`、`[x]`，表格和分隔线改用 ASCII 字符，不会因为编码报错。
- `table` 的单元格按字符串显示，`None` 显示为空。某一行的单元格比表头多时抛 `ValueError`。单元格太宽时在列内折行，不截断；不是终端时 rich 按 80 列（或 `$COLUMNS`）排版，所以一行数据可能占几行，需要逐行处理的机器输出请用 `echo`。
- 每次调用都按当时的 `sys.stdout`、`sys.stderr` 输出，所以 `contextlib.redirect_stdout` 和测试里的替换都能捕获到。

## 等待提示

```python
with tui.spinner("Downloading the release"):
    await download(url, target)

with tui.progress("Copying files", total=len(files)) as bar:
    for path in files:
        await copy(path)
        bar.advance()
```

- `spinner(label)` 用于不知道要多久的工作，`progress(label, *, total=None)` 用于能计数的工作；`total` 不知道时传 `None`。块里拿到的 `ProgressBar` 有 `advance(amount=1)` 和 `update(*, completed=None, total=None, label=None)`。
- 在终端里，rich 在自己的线程刷新，所以块里可以 `await`，提示照样在动；块里 `print`、`echo` 的内容由 rich 转到提示上方显示，制表符显示成空格（只影响屏幕：输出不是终端时没有动画，也不经过转发）。等待提示可以嵌套，例如进度条的每一步里再用 `spinner`。`spinner` 结束后消失，`progress` 保留最后一行。
- 流本身不是终端（按它自己的 `isatty()`；设了 `FORCE_COLOR` 也不算）时不画动画：`spinner` 打印一行 `label`；`progress` 开始时打印 `label`，正常结束时打印 `label: 已完成/总数`。块里抛出的异常照常向外传，不打印结束行。
- 用 `ext://sys.stdout` 配置的日志 handler 在启动时就拿住了原来的流，提示显示期间写日志会盖住提示所在的那一行；这只影响显示。
- 直接写终端的内容不经过 rich，会被下一次刷新擦掉，例如 `sudo` 问密码：提示一闪就没了，程序却在等输入。所以可能在终端上问人的命令（要密码的 `sudo`、脚本里的 `read`）不要放在等待提示里运行，改为先用 `info` 写一行正在做什么再运行，提示就会留在这行下面。

## 提问

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

`unprivileged` 和 `reload_server` 是命令自己的业务函数：前者在端口小于 1024 时 `raise ValueError("Ports below 1024 need root.")`。`key` 让这些问题可以[预置答案](#预置答案无人值守)，不需要无人值守的问题可以不给。

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `ask(label, *, default=None, type=str, choices=None, validate=None, required=True, secret=False, confirm_secret=False, help=None, key=None)` | `type` 转换后的值 | 读一行文字 |
| `confirm(label, *, default=False, assume_yes=False, help=None, key=None)` | `bool` | 是或否 |
| `choose(label, options, *, default=None, match=None, invalid=None, validate=None, key=None)` | 选中的值 | 编号列表里选一个 |
| `choose_many(label, options, *, default=(), key=None)` | 选中值的列表 | 选任意多个 |

- `ask` 的空答：给了 `default` 就返回它（空字符串也算）；没给且 `required=False` 返回 `None`；否则提示「此项必填」再问。`type` 把文字转成值，抛 `ValueError` 时说明原因再问（`int`、`float` 有专门的说明）；`choices` 与转换后的值比较；`validate` 抛 `ValueError` 就把它的消息显示出来再问。
- `secret=True` 时输入不回显、不去掉首尾空格，默认值也不显示；`confirm_secret=True` 再输一次，两次不一致就都重输。
- `confirm` 接受 y、yes、n、no 和当前语言的「是 / 否」。命令有自己的 `--yes` 时把它传给 `assume_yes`，为真就不问、直接通过。
- `choose` / `choose_many` 的选项可以是普通值（按文字显示，Enum 成员显示它的值），也可以是 `(值, 显示文字)`。回答不区分大小写。手输的回答按人看到的匹配：先按显示文字，再按编号，最后才按值——`(值, 文字)` 选项的值不显示，所以选项 `[(17, "alice"), (1, "carol")]` 手输 `1` 是第一项 alice；[预置答案](#预置答案无人值守)由知道值的人写，先按值，再按文字，再按编号。选项 `["3", "1"]` 回答 `1`，两种情况都选中 `"1"`（它的文字就是 `1`）；`choose_many` 用逗号或空格分隔多个，重复的只算一次。`match(回答)` 让调用方补充解析（例如把 `zh` 解析成 `zh-Hans`），返回 `None` 表示不认识；`invalid` 替换「请输入 1 到 N 之间的编号」这句提示；`validate` 抛 `ValueError` 时显示它的消息，重新选择。`default` 必须是选项之一，否则调用时抛 `ValueError`。`choose` 的提示符显示默认项的编号（`[1]: `），`choose_many` 显示默认选中的全部编号（`[1,2]: `），回车就是它们。
- 提示和出错说明写在说明文字的流上：平时是 stdout，`raw_stdout` 命令里是 stderr。

### 取消与非终端

- 回答时按 Ctrl-C 或输入结束（Ctrl-D、管道关闭）抛 `tui.Cancelled`，`reason` 分别是 `"interrupt"` 和 `"end-of-input"`。在 `asyncio.run` 里（App 命令都是）也是按一次就生效：读取期间 tui 临时恢复 Python 自己的 Ctrl-C 处理，读完再换回事件循环的。App 命令里不用自己处理：CLI 在 stderr 写「已中止。」并以 1 退出。需要区别对待时（例如输入结束就用默认值、Ctrl-C 才退出）自己捕获并看 `reason`。
- stdin 和提示所在的流（平时是 stdout，`raw_stdout` 命令里是 stderr）都是终端才提问。其他情况（cron、CI、`< /dev/null`、管道、程序调用命令并接走输出、`> out.txt`）不读 stdin：有[预置答案](#预置答案无人值守)就用它；否则有默认值的问题直接用默认值，并把「问题: 默认值」写一行（`secret` 显示为 `***`），`confirm` 用它的 `default`；都没有的问题抛 `tui.NotInteractive`（它是 `ValueError`，CLI 按普通错误报出并以 1 退出），问题带 `key` 时消息里写明该设哪个变量。
- 只看 stdin 不够：程序调用命令并接走它的输出时，stdin 常常继承自终端，问题却写进了被接走的输出，命令对着终端空等。所以 `./run.sh ops menu 2>&1 | tee session.log` 也不提问；要留下操作记录，用预置答案，或用 `script -c "./run.sh ops menu" session.log` 录下整个终端会话。`raw_stdout` 命令的提示走 stderr，所以把它的数据重定向到文件（`command > data.json`）时照常提问。启动时就被关闭的 stdin（`0<&-`）按非终端处理。`db migrate`、`makemigrations` 的数据库结构问题按同一条规则，并且没有预置答案：不能提问时，要人来决定的问题（首次使用、状态丢失、改名或删除）直接报错；只是有待执行的迁移、要选执行范围时不问，执行全部待执行的迁移，和以前一样。
- 不从管道按行读答案，是因为按顺序对应问题很脆弱：命令按条件跳过一个问题、调整顺序或新增一个问题，后面的答案就整体错位且不报错；stdin 开着却没人写时还会一直卡住。

### 预置答案（无人值守）

给问题一个 `key`，就能事先用环境变量给出答案，和 Debian 安装程序的预置答案（preseed）同一思路：

```sh
OLDMAN_ANSWER_ADD_SITE_DOMAIN=example.org OLDMAN_ANSWER_ADD_SITE_PORT=9000 ./run.sh ops add-site
```

- 变量名是 `tui.answer_variable(key)`：`OLDMAN_ANSWER_` 加上 key 转大写、其他字符连续换成一个 `_`，例如 `startproject.type` → `OLDMAN_ANSWER_STARTPROJECT_TYPE`。只差在其他字符上的 key 对应同一个变量（`add-site.port` 和 `add_site.port`），同一次运行里问到的 key 要在字母或数字上有区别。key 只能由字母、数字、`.`、`_`、`-` 组成并以字母或数字开头，否则调用时抛 `ValueError`。
- 设了变量的问题不再提问，在终端里也一样，只写一行「问题: 答案 (变量名)」（`secret` 显示为 `***`）。
- 预置答案与手输的答案一样检查：`ask` 按 `type`、`choices`、`validate`；`confirm` 接受 1/true/yes/y 和 0/false/no/n；`choose` / `choose_many` 先按值、再按显示文字、再按编号匹配（以及 `match` 认得的写法），`choose` 再过 `validate`。不合格就抛 `ValueError` 并写出变量名，不会退回去提问——无人值守时没人能回答。设成空字符串等于空答：用默认值，没有默认值又必填就报错。
- `confirm` 的 `assume_yes=True` 优先于预置答案：命令行上的 `--yes` 比环境里的设置更明确。
- 菜单没有 key，始终要人来选；只给需要无人值守的问题起 key。框架自己命令（`startproject`、`startapp`、`startservice`）的变量见 [CLI 参考](cli.md#项目级命令)。

### 测试

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

`apps.sites` 是示意的 App 名，换成上面那个命令所在的模块。`simulate_input(answers)` 按顺序给出答案，并在块内捕获 stdout 和 stderr（`terminal.stdout`、`terminal.stderr`），内容和终端上看到的一样：提示后面跟着答案，`secret` 的答案不显示。答案写成 `KeyboardInterrupt` 或 `EOFError` 就在那一问取消。块里的问题一律按终端处理，即使测试进程的 stdin、stdout 不是终端；答案用完还有人提问时抛 `RuntimeError` 并写出是哪个提示，测试不会卡在真实终端上等输入。`terminal.remaining` 是没被用到的答案。

预置答案优先于 `simulate_input` 给的回答（测试预置答案时正要这样）。所以开发者 shell 里留着某个 `OLDMAN_ANSWER_*` 时，带同一 key 的问题会被它回答，测试就错位了。测试开始前在块内删掉这些变量，例如 `with patch.dict(os.environ):` 里把以 `tui.ANSWER_ENV_PREFIX` 开头的变量删掉（块结束时自动恢复）；用 `CliRunner().invoke(..., env=...)` 时它只添加变量，要删掉的变量得写成 `None`。

## 表单与菜单

运维工具常见的形状：一个菜单，选中的动作先收一组参数，再执行。

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

`write_site`、`discover_checks`、`reload_nginx` 是工具自己的业务（async 函数）。

### 表单

- `Field(key, label, ...)` 的其余参数与 `ask` 相同；`type=bool` 的字段用 `confirm` 问。`ask_form(fields, *, key_prefix=None, remember=None)` 按顺序提问，返回 `{key: 值}`；`key` 重复时抛 `ValueError`。
- 每个字段都是一个带 key 的问题，key 是 `{key_prefix}.{字段 key}`（没有 `key_prefix` 时就是字段 key），所以能像任何问题一样[预置答案](#预置答案无人值守)：上例里 `OLDMAN_ANSWER_ADD_SITE_PORT=9000` 就回答了端口。字段 key 不能组成合法的问题 key 时，提问之前就抛 `ValueError`。
- `remember` 是一个 JSON 文件路径（可以用 `~`）：表单完成后把答案写进去，下次作为这些问题的默认值；文件里别的键原样保留。记住的答案用作默认值之前，先像手输的答案一样过一遍字段的 `type`、`choices`、`validate`（`type=bool` 的字段要求是 `true`/`false`）：规则可能改过，文件也可能被手工改过；不合格就提示一次，这次改用字段自己的默认值；必填字段记住的空字符串也算不合格。设了预置答案的字段直接用预置答案，不看也不检查记住的答案。`secret` 字段和不是 JSON 原生类型（str、int、float、bool）的值不写。文件内容不是合法 JSON 对象时提示一次，这次不用它，也不覆盖它。

### 菜单

- `Menu(title, items)`；`Item(label, *, action=None, submenu=None, load=None)` 三者必须恰好给一个：`action` 是选中后 await 的 async 函数，`submenu` 是固定的子菜单，`load` 是选中时才 await 来生成子菜单的 async 函数（菜单内容来自插件、远程清单等）。菜单项来自远程文件时见 [远程文件](remote.md)。给错数量或菜单没有项时，构造时就抛 `ValueError`。
- `await run_menu(menu, *, after_action="return", back_label=None, quit_label=None)`：显示标题分隔线和编号项，`0` 离开——顶层是「退出」，子菜单是「返回」（两个参数替换这两个词）。回答可以是项的文字或编号，先按文字找。在菜单处按 Ctrl-C 或输入结束，等于选 `0`。
- `after_action="return"` 时动作执行完回到菜单；`"exit"` 时执行完一个动作就结束整个菜单（包括外层）。动作或 `load` 抛出异常时，在 stderr 显示它的消息，回到选它的那一层菜单；调用栈以 DEBUG 级别写进日志（logger `oldman.cli.tui.menus`）：日志级别是 DEBUG 时屏幕和日志文件里都能看到，平时屏幕上只有那一行。日志级别由 `logging.level` 决定，它为空时跟随 `core.debug`；动作或 `load` 里的 `Cancelled`（例如表单里按了 Ctrl-C）直接回到菜单，不当作错误。
- 菜单一定要交互：按上面的规则不能提问时抛 `NotInteractive`。无人值守的入口请另写一个带参数的命令，调用同一批业务函数。

## 与 `raw_stdout` 命令

`raw_stdout = True` 的命令 stdout 只给数据（见 [CLI 参考](cli.md#命令生命周期)）。这类命令里，除了 `echo`，tui 的所有输出（说明、状态行、表格、分隔线、等待提示）都改写到 stderr；等待提示显示期间也只接管 stderr，写到 stdout 的数据不会被带走。

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

`read_sites` 同样是命令自己的业务函数。`./run.sh ops dump-sites > sites.json` 得到的文件里只有 JSON，「Reading the site list」和「Printed …」留在终端上。
