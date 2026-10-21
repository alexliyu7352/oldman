# Operations primitives

`oldman.ops` provides operations independent of business logic for server maintenance and deployment tools: repeatable configuration-file edits, operating-system identity, and systemd unit management. The tool decides what to change and which commands need `sudo`. Choose external-command interfaces according to whether a person may need to answer; see [Processes and background tasks](background.md#external-commands). Interactive commands, such as `sudo` asking for a password or a script using `read`, use `run_foreground`; see [Processes and background tasks](background.md#foreground-commands). The systemd operations and remote scripts below both use it. Unattended commands requiring a timeout and whole-group cleanup use `run_subprocess_exec`. Use [Remote files](remote.md) to fetch remote files and attach them to menus, and [Backend HTTP client](http-client.md) for other HTTP requests, rather than implementing those operations here. See [Terminal interaction](tui.md) for terminal interaction.

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

Run this command as a user who can write to `/etc`. Adding `sudo` only to `systemctl` is this tool's own choice.

## Configuration files

| Function | Behavior |
| --- | --- |
| `edit_marked_block(path, marker, content, *, follow_symlinks, comment="#")` | This places `content` between `# >>> marker` and `# <<< marker`. It replaces an existing marked block, appends one if absent, and creates the file if needed. |
| `set_directive(path, key, value, *, follow_symlinks, separator=" ", comment="#")` | This sets the key to `value` in a `key value` file such as sshd_config or sysctl.conf. |
| `read_directive(path, key, default=None, *, separator=" ", comment="#")` | This reads the first uncommented occurrence of the key, returning `default` if the file or key is absent. |

- Both writing functions replace the complete file through `atomic_write`, so readers see either its old contents or its new contents. Unchanged content is not written and returns `False`; a change returns `True`. Use the result to decide whether to reload the service.
- Supply `follow_symlinks` explicitly. `True` edits the link's target; `False` replaces the link at `path` with a regular file, as `atomic_write` does. For links managed by a package manager or alternatives under `/etc`, decide carefully which file you intend to change.
- `edit_marked_block` is repeatable: a second call with identical content does not change the file. Trailing whitespace in `content` is stripped. Markers match in full, so `OPCACHE` does not replace an `OPCACHE_EXTRA` block. Set `comment` to the configuration file's own comment syntax, such as `;` for ini files.
- `set_directive` rewrites **every line** for that key as `key<separator>value`, including commented lines whose marker touches the key, such as `#Port 22`. Otherwise an earlier example and a later setting might disagree. A comment with whitespace after the marker, such as `# Port numbers below…`, is explanatory text and remains unchanged. If there is no matching line, the setting is appended. Keys are case-insensitive. Matching keys in conditional sections such as sshd's `Match` are also rewritten; use `edit_marked_block` or your own handling for such files.
- `separator` specifies the text between key and value when writing, such as `" = "` in sysctl.conf. Reading and matching ignore surrounding whitespace, so `"="` is sufficient to read `net.core.somaxconn = 4096`.

## Operating-system identity

`os_release(path=None)` returns os-release contents, for example `{"ID": "ubuntu", "VERSION_ID": "22.04", "PRETTY_NAME": "Ubuntu 22.04.4 LTS", ...}`, with quotes around values removed. Without `path`, it follows os-release(5): read `/etc/os-release` first, then `/usr/lib/os-release` if absent. If neither exists, return an empty dictionary.

## systemd

| Function | Behavior |
| --- | --- |
| `await systemd.is_active(unit, *, command=SYSTEMCTL)` | This checks whether the unit is running through `systemctl is-active --quiet`. |
| `await systemd.restart(*candidates, command=SYSTEMCTL)` | This restarts the first running candidate and returns its name. If none is running, it returns `None` without starting any. |
| `await systemd.reload(unit, *, command=SYSTEMCTL)` | This asks the unit to reload its configuration. |
| `await systemd.daemon_reload(*, command=SYSTEMCTL)` | This asks systemd to reread unit files. |

- `command` specifies how to run `systemctl`, defaulting to `("systemctl",)`. Pass `("sudo", "systemctl")` when privileges are required. Tests can pass a path to a fake `systemctl` script.
- systemctl runs in the foreground through `run_foreground` and shares the tool's terminal, allowing `sudo` to ask for a password normally. Without a terminal, as in cron or systemd timers, `sudo` cannot request a password; configure passwordless sudo or run the tool as root. If `sudo` may prompt, do not call these functions inside `tui.spinner` or `tui.progress`: animation refresh can erase the `sudo` prompt. See [Terminal interaction](tui.md#waiting-indicators). systemctl is quick; print the operation with `tui.info` first, then call it.
- `restart` candidates account for one service having different names on different systems, such as `restart("ssh", "sshd")`.
- Failed `restart`, `reload`, and `daemon_reload` operations raise `subprocess.CalledProcessError`, with systemctl's text error output in `stderr`. `is_active` returns `False` when the unit is not running.
- If the first program in `command`, either `systemctl` or `sudo`, is missing, all four functions raise `FileNotFoundError`. A machine without systemd is different from an inactive unit; returning `False` would let `restart` silently do nothing. When using `sudo`, a missing `systemctl` instead makes `sudo` exit nonzero. The same happens when `sudo` itself fails, for example because it has no terminal for a password prompt. In those cases `is_active` returns `False`, `restart` restarts nothing and returns `None`, and `reload` and `daemon_reload` raise `CalledProcessError`. This path cannot distinguish a system without systemd from an inactive unit.

<!-- source: zh/developers/ops.md @ 8c13fdcf -->
