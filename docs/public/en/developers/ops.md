# Operations primitives

`oldman.ops` provides business-independent basics for server maintenance/deployment tools: repeatable configuration edits, OS identity, and systemd operations. The tool chooses what to change and which commands need sudo. Select external-command APIs by [Processes and background tasks](background.md#external-commands): terminal interaction (sudo prompts, shell read) uses [Processes and background tasks](background.md#foreground-commands), as systemd and remote scripts below do. Unattended commands needing timeouts/group cleanup use run_subprocess_exec. Use [Remote files](remote.md) for fetching/menu integration, [Backend HTTP client](http-client.md) for other HTTP, and [Terminal interaction](tui.md) for interaction rather than reimplementing them here.

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

Run this command as a user able to write /etc. Adding sudo only to systemctl is this tool's own choice.

## Configuration files

| Function | Behavior |
| --- | --- |
| `edit_marked_block(path, marker, content, *, follow_symlinks, comment="#")` | Places content between `# >>> marker` and `# <<< marker`: replaces an existing marked block, appends if absent, creates the file if missing |
| `set_directive(path, key, value, *, follow_symlinks, separator=" ", comment="#")` | Sets a key to value in key/value-style files such as sshd_config/sysctl.conf |
| `read_directive(path, key, default=None, *, separator=" ", comment="#")` | Reads the first uncommented matching key, returning default when the file/key is absent |

- Both writers replace whole files through atomic_write, so readers see either old or new contents. Unchanged content causes no write and returns False; changes return True, allowing conditional service reload.
- Explicit follow_symlinks is required: True edits the link target; False replaces the link at path with a regular file, as atomic_write does. Decide carefully which file to change for /etc links maintained by package managers/alternatives.
- edit_marked_block is repeatable: identical content does not change the file again. Trailing content whitespace is stripped. Markers match completely: OPCACHE does not replace OPCACHE_EXTRA. Set comment to the file's own syntax, such as ; for ini.
- set_directive rewrites **every line** for the key as key<separator>value, including commented keys with adjacent comment markers such as #Port 22. Otherwise early examples and later settings could conflict. Comments with whitespace after the marker, such as # Port numbers below…, are explanatory and untouched. Missing keys append. Key matching is case-insensitive. Same-named keys in conditional sections such as sshd Match also change; use edit_marked_block or custom handling for those files.
- separator specifies text between key/value when writing, such as `" = "` for sysctl.conf. Reading/matching ignores surrounding whitespace, so `"="` reads net.core.somaxconn = 4096.

## Operating-system identity

os_release(path=None) returns os-release contents, such as `{"ID": "ubuntu", "VERSION_ID": "22.04", "PRETTY_NAME": "Ubuntu 22.04.4 LTS", ...}`, with surrounding value quotes removed. Without path, os-release(5) order is /etc/os-release then /usr/lib/os-release; neither present returns an empty dict.

## systemd

| Function | Behavior |
| --- | --- |
| `await systemd.is_active(unit, *, command=SYSTEMCTL)` | Whether the unit is running (`systemctl is-active --quiet`) |
| `await systemd.restart(*candidates, command=SYSTEMCTL)` | Restarts the first running candidate and returns its name; returns None if none run, without starting them |
| `await systemd.reload(unit, *, command=SYSTEMCTL)` | Reloads unit configuration |
| `await systemd.daemon_reload(*, command=SYSTEMCTL)` | Makes systemd reread unit files |

- command specifies how to run systemctl, default `("systemctl",)`. For privilege escalation, pass `("sudo", "systemctl")`. Tests may pass a fake systemctl script path.
- systemctl runs in the foreground through run_foreground, sharing the terminal so sudo can prompt normally. Without a terminal (cron/systemd timers), configure passwordless sudo or run as root. If sudo may prompt, do not wrap these calls in tui.spinner/tui.progress: animation refresh can erase prompts; see [Terminal interaction](tui.md#waiting-indicators). systemctl is quick, so print the operation with tui.info before calling.
- restart candidates handle OS-specific names for one service, such as restart("ssh", "sshd").
- restart/reload/daemon_reload failures raise subprocess.CalledProcessError with text systemctl stderr. is_active returns False for inactive units.
- If the first executable (systemctl or sudo) is absent, all four raise FileNotFoundError. No systemd is different from an inactive unit; returning False would make restart silently do nothing. Under sudo, missing systemctl instead makes sudo exit nonzero, as do sudo's own failures such as unavailable password prompts. Then is_active returns False, restart does nothing/returns None, and reload/daemon_reload raise CalledProcessError. This path cannot distinguish missing systemd from an inactive unit.

<!-- source: zh/developers/ops.md @ 8c13fdcf -->
