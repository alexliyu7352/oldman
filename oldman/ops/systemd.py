"""systemd units: ask whether one runs, restart or reload it, reload the unit files.

`command` is how `systemctl` is run, `("systemctl",)` by default. Whether it needs `sudo` is the
program's decision: pass `("sudo", "systemctl")`. Tests pass the path of a stand-in script.
systemctl runs in the foreground on the tool's terminal, so `sudo` can ask for a password.
When the first program of `command` is missing, every function raises `FileNotFoundError`. Under
`sudo`, a missing `systemctl` is sudo's own failure instead, as is sudo failing by itself (no
terminal to ask for the password): `is_active` answers False, so `restart` returns None without
restarting anything, and `reload` / `daemon_reload` raise `subprocess.CalledProcessError`.
"""

from __future__ import annotations

from collections.abc import Sequence

from oldman.processes import run_foreground

SYSTEMCTL: tuple[str, ...] = ("systemctl",)


async def _systemctl(command: Sequence[str], *arguments: str, check: bool) -> int:
    if not command:
        raise ValueError("command must name the systemctl program")
    # In the foreground so sudo can ask for a password. sudo reads it from the terminal itself,
    # so capturing the output does not get in its way.
    completed = await run_foreground(*command, *arguments, capture_output=True, text=True, check=check)
    return completed.returncode


async def is_active(unit: str, *, command: Sequence[str] = SYSTEMCTL) -> bool:
    """Whether `unit` is running (`systemctl is-active --quiet`).

    When the program of `command` is missing this raises rather than answering False: "no
    systemd here" is not "the unit is stopped", and `restart` would otherwise do nothing without a
    word. Behind `sudo` that cannot be told apart from a stopped unit.
    """
    return await _systemctl(command, "is-active", "--quiet", unit, check=False) == 0


async def restart(*candidates: str, command: Sequence[str] = SYSTEMCTL) -> str | None:
    """Restart the first of `candidates` that is running and return its name; None if none is.

    For a service named differently across systems, such as `restart("ssh", "sshd")`. A unit that
    is not running is not started. A failing restart raises `subprocess.CalledProcessError`,
    whose `stdout` and `stderr` hold the command's output.
    """
    if not candidates:
        raise ValueError("restart needs at least one unit")
    for unit in candidates:
        if await is_active(unit, command=command):
            await _systemctl(command, "restart", unit, check=True)
            return unit
    return None


async def reload(unit: str, *, command: Sequence[str] = SYSTEMCTL) -> None:
    """Have `unit` reload its configuration; raises `subprocess.CalledProcessError` when it fails."""
    await _systemctl(command, "reload", unit, check=True)


async def daemon_reload(*, command: Sequence[str] = SYSTEMCTL) -> None:
    """Make systemd read changed unit files; raises `subprocess.CalledProcessError` when it fails."""
    await _systemctl(command, "daemon-reload", check=True)


__all__ = ["SYSTEMCTL", "daemon_reload", "is_active", "reload", "restart"]
