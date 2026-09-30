# 运维原语（ops）

`oldman.ops` 给服务器维护、部署工具提供与具体业务无关的基础操作：改配置文件（可以反复执行）、读操作系统标识、操作 systemd 单元。改什么、哪条命令要 `sudo`，由工具自己决定。执行外部命令按[对面有没有人](background.md#外部命令)选：要在终端上和人交互的命令（`sudo` 问密码、脚本里的 `read`）用 [`run_foreground`](background.md#前台命令)，下面的 systemd 和远程脚本都用它；不需要人参与、要超时和整组清理的用 `run_subprocess_exec`。取远程文件、把远程文件挂进菜单用 [远程文件](remote.md)，其他 HTTP 请求用 [后端 HTTP 客户端](http-client.md)，这里不另写。交互界面见 [终端交互](tui.md)。

```python
from oldman import ops
from oldman.cli import Command, tui

SUDO_SYSTEMCTL = ("sudo", "systemctl")


class ChangeSshPort(Command):
    """Move sshd to another port."""

    name = "ssh-port"
    help = "Change the port sshd listens on."

    async def handle(self) -> None:
        current = ops.read_directive("/etc/ssh/sshd_config", "Port", "22")
        port = tui.ask("New SSH port", type=int, default=43589, help="Currently %s." % current)
        changed = ops.set_directive("/etc/ssh/sshd_config", "Port", str(port), follow_symlinks=True)
        release = ops.os_release()
        if release.get("ID") == "ubuntu" and float(release.get("VERSION_ID", "0")) >= 22.04:
            ops.edit_marked_block(
                "/etc/systemd/system/ssh.socket.d/override.conf",
                "PORT",
                "[Socket]\nListenStream=\nListenStream=%d" % port,
                follow_symlinks=False,
            )
            await ops.systemd.daemon_reload(command=SUDO_SYSTEMCTL)
        if changed:
            restarted = await ops.systemd.restart("ssh", "sshd", command=SUDO_SYSTEMCTL)
            if restarted is None:
                tui.warning("No SSH service is running; restart it by hand.")
            else:
                tui.success("%s now listens on %d" % (restarted, port))
```

这个命令要以能写 `/etc` 的用户运行；`sudo` 只加在 `systemctl` 上，是这个工具自己的选择。

## 配置文件

| 函数 | 行为 |
| --- | --- |
| `edit_marked_block(path, marker, content, *, follow_symlinks, comment="#")` | 把 `content` 放进 `# >>> marker` 与 `# <<< marker` 两行之间：已有这个标记的块就替换，没有就追加到末尾，文件不存在就创建 |
| `set_directive(path, key, value, *, follow_symlinks, separator=" ", comment="#")` | 让 `key value` 风格的文件（sshd_config、sysctl.conf 等）里这个键取 `value` |
| `read_directive(path, key, default=None, *, separator=" ", comment="#")` | 取第一条没被注释掉的该键的值；文件不存在或没有这个键时返回 `default` |

- 两个写入函数都通过 `atomic_write` 整体替换文件，读的人只会看到改前或改后的内容；内容没有变化时不写文件，返回 `False`，改了返回 `True`，可以据此决定要不要重载服务。
- `follow_symlinks` 必须显式传：`True` 改写符号链接指向的文件，`False` 把 `path` 处的链接换成普通文件（与 `atomic_write` 相同）。`/etc` 下由包管理器或 alternatives 维护的链接，要想清楚改的是哪一个。
- `edit_marked_block` 可以反复执行：同样的内容第二次不改文件；`content` 末尾的空白会被去掉。标记要完整匹配：`OPCACHE` 不会替换 `OPCACHE_EXTRA` 的块。`comment` 换成配置文件自己的注释符，例如 ini 的 `;`。
- `set_directive` 把这个键的**每一行**都改成 `key<separator>value`，包括被注释掉的（注释符紧贴键名，如 `#Port 22`）：否则文件里前面的示例行和后面另一条设置可能各说各话。注释符后面有空格的（`# Port numbers below…`）是说明文字，不动。一行都没有时追加到末尾。键名不区分大小写。sshd 的 `Match` 这类条件段里的同名键也会被改，这类文件请用 `edit_marked_block` 或自己处理。
- `separator` 是写入时键与值之间的内容，例如 sysctl.conf 用 `" = "`；读和匹配时会忽略它两边的空白，所以读 `net.core.somaxconn = 4096` 时传 `"="` 即可。

## 操作系统标识

`os_release(path=None)` 返回 os-release 的内容，例如 `{"ID": "ubuntu", "VERSION_ID": "22.04", "PRETTY_NAME": "Ubuntu 22.04.4 LTS", ...}`，值两边的引号已去掉。不传 `path` 时按 os-release(5) 先读 `/etc/os-release`，没有再读 `/usr/lib/os-release`，都没有返回空字典。

## systemd

| 函数 | 行为 |
| --- | --- |
| `await systemd.is_active(unit, *, command=SYSTEMCTL)` | 单元是否在运行（`systemctl is-active --quiet`） |
| `await systemd.restart(*candidates, command=SYSTEMCTL)` | 重启候选中第一个正在运行的单元，返回它的名字；都没在运行时返回 `None`，不会去启动它们 |
| `await systemd.reload(unit, *, command=SYSTEMCTL)` | 让单元重新读取配置 |
| `await systemd.daemon_reload(*, command=SYSTEMCTL)` | 让 systemd 重新读取单元文件 |

- `command` 是运行 `systemctl` 的方式，默认 `("systemctl",)`；需要提权时传 `("sudo", "systemctl")`。测试里可以传一个假 `systemctl` 脚本的路径。
- systemctl 经 `run_foreground` 在前台运行，和工具共用终端：`sudo` 要密码时照常在终端上问。没有终端（cron、systemd 定时器）时 `sudo` 问不了密码，要么配免密 sudo，要么以 root 运行工具。`sudo` 可能要密码时，不要把这些函数包在 `tui.spinner` / `tui.progress` 里调用：`sudo` 的提示会被动画刷新擦掉，见[等待提示](tui.md#等待提示)。systemctl 很快，先用 `tui.info` 写一行正在做什么再调用即可。
- `restart` 的候选用于同一服务在不同系统上名字不同的情况，例如 `restart("ssh", "sshd")`。
- `restart`、`reload`、`daemon_reload` 失败时抛 `subprocess.CalledProcessError`，`stderr` 里是 systemctl 的错误输出（文本）；`is_active` 在单元没运行时返回 `False`。
- `command` 的第一个程序（`systemctl` 或 `sudo`）找不到时，四个函数都抛 `FileNotFoundError`：机器上没有 systemd 不等于单元没在运行，返回 `False` 会让 `restart` 什么都不做也不报错。经 `sudo` 运行时，缺的若是 `systemctl`，报错的是 `sudo` 本身（非零退出），`sudo` 自己失败（例如没有终端问不了密码）也一样：`is_active` 返回 `False`，于是 `restart` 什么都不重启、返回 `None`，`reload`、`daemon_reload` 抛 `CalledProcessError`。这时分不出是没有 systemd 还是单元没在运行。
