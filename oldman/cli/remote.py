"""Remote files for command-line tools: one file, one task, fetched from a base address.

A tool's menu points at files by path under one base: an ``http(s)://`` address (a GitHub raw
URL with a tag in it, a file server; ``user:pass@`` is allowed) or a local directory while
developing. A Python file exports ``async def run()`` (one task) or ``async def menu()`` (its own
``tui.Menu``) and runs inside the tool's command, so the database, Redis and settings are already
set up; a script runs as a child process. Downloaded files are cached per base address and only
change on ``refresh()``. See docs/public/zh/developers/remote.md.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Literal
from urllib.parse import quote, unquote, urlsplit

from oldman.cli.tui.menus import Menu


class RemoteFileError(Exception):
    """A remote file could not be downloaded."""


@dataclass(frozen=True)
class Refreshed:
    """What `refresh()` did: the files it downloaded again, and the ones it could not with the reason."""

    updated: tuple[str, ...]
    failed: dict[str, str]


def _relative_path(path: str) -> str:
    """The same string becomes a URL suffix and a cache path, so it has to stay inside both."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("a remote file path must be a non-empty string")
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"a remote file path must be relative and stay inside the base: {path!r}")
    if not relative.parts:
        # "." names the base itself: its cache path is the cache directory, which a download would replace.
        raise ValueError(f"a remote file path must name a file under the base: {path!r}")
    return relative.as_posix()


class RemoteFiles:
    """Files under one base address, for `tui.Item(load=...)` and `tui.Item(action=...)`."""

    def __init__(
        self,
        base: str | os.PathLike[str],
        *,
        cache_dir: str | os.PathLike[str],
        proxy_url: str | None = None,
    ) -> None:
        self._url: str | None = None
        self._directory: Path | None = None
        self._secrets: tuple[str, ...] = ()
        if isinstance(base, str) and base.lower().startswith(("http://", "https://")):
            from oldman.contrib.http._logging import redact_url

            parts = urlsplit(base)
            if not parts.hostname or parts.query or parts.fragment:
                raise ValueError("a remote base address needs a host and no query or fragment")
            self._url = base.rstrip("/")
            # Credentials only go into the request; everything shown uses the redacted address.
            self._shown_base = redact_url(self._url)
            # A password may come back as typed, decoded or re-quoted by the HTTP client; the whole
            # userinfo first, so the longer form is replaced before its parts.
            userinfo = parts.netloc.rpartition("@")[0]
            password = parts.password or ""
            forms = {userinfo, password, unquote(password), quote(unquote(password), safe="")}
            self._secrets = tuple(sorted((form for form in forms if form), key=len, reverse=True))
        else:
            self._directory = Path(base).expanduser().resolve()
            self._shown_base = str(self._directory)
        # Keyed by the base address, so a base with another tag in it never serves this one's files.
        self._cache = Path(cache_dir).expanduser() / hashlib.sha256(self._shown_base.encode()).hexdigest()[:16]
        self._proxy_url = proxy_url
        self._modules: dict[str, ModuleType] = {}

    def _shown(self, relative: str) -> str:
        return f"{self._shown_base}/{relative}"

    def _scrub(self, text: str) -> str:
        # By substring: a very short password also hides the same characters elsewhere in the message,
        # such as a port number. That only garbles the message and never shows the password; left as is.
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    async def fetch(self, path: str) -> Path:
        """The local file for `path`: the file itself under a local base, otherwise the cached copy,
        downloaded the first time it is asked for."""
        relative = _relative_path(path)
        if self._directory is not None:
            local = self._directory / relative
            if not local.is_file():
                raise FileNotFoundError(f"{relative} is not a file in {self._directory}")
            return local
        cached = self._cache / relative
        if not cached.is_file():
            await self._download(relative, cached)
        return cached

    async def refresh(self) -> Refreshed:
        """Download every cached file of this base again.

        Each file is replaced on its own; files do not depend on each other. One that cannot be
        downloaded — the base no longer has it, the server fails — is skipped and reported in
        `failed`, its cached copy stays so the tool keeps working offline, and the others are still
        refreshed: stopping at it would stop every later refresh at the same file. A Python file is
        loaded again the next time its item is chosen. A local base has nothing to do.
        """
        updated: list[str] = []
        failed: dict[str, str] = {}
        if self._directory is not None or not self._cache.is_dir():
            return Refreshed(updated=(), failed=failed)
        for file in sorted(self._cache.rglob("*")):
            # atomic_write's temporary files are ".<name>.<token>.tmp"; one left by a crash is not a remote file.
            if not file.is_file() or (file.name.startswith(".") and file.name.endswith(".tmp")):
                continue
            relative = file.relative_to(self._cache).as_posix()
            try:
                await self._download(relative, file)
            except RemoteFileError as problem:
                failed[relative] = str(problem)
                continue
            updated.append(relative)
        return Refreshed(updated=tuple(updated), failed=failed)

    def menu(self, path: str) -> Callable[[], Awaitable[Menu]]:
        """For `tui.Item(load=...)`: the file's `menu()`, loaded when the item is chosen."""
        relative = _relative_path(path)

        async def load() -> Menu:
            built = await self._entry(relative, "menu")()
            if not isinstance(built, Menu):
                raise TypeError(f"{self._shown(relative)}: menu() returned {type(built).__name__}, not tui.Menu")
            return built

        return load

    def action(self, path: str) -> Callable[[], Awaitable[None]]:
        """For `tui.Item(action=...)`: the file's `run()`."""
        relative = _relative_path(path)

        async def run() -> None:
            await self._entry(relative, "run")()

        return run

    def script(self, path: str, *args: str, interpreter: str, check: bool = True) -> Callable[[], Awaitable[None]]:
        """For `tui.Item(action=...)`: run `interpreter <file> *args` as a child process.

        The script runs in the foreground on the tool's terminal and environment: its output shows
        as it comes, `sudo` can ask for a password and preset answers reach it. With `check`, a
        non-zero exit raises `subprocess.CalledProcessError`.
        """
        relative = _relative_path(path)
        if not interpreter:
            raise ValueError("interpreter must name the program that runs the script, such as bash")

        async def run() -> None:
            from oldman.processes import run_foreground

            file = await self.fetch(relative)
            # On the tool's terminal, so sudo and read reach the person running the tool.
            completed = await run_foreground(interpreter, file, *args)
            if check and completed.returncode != 0:
                raise subprocess.CalledProcessError(completed.returncode, [interpreter, relative, *args])

        return run

    async def _download(self, relative: str, target: Path) -> None:
        from oldman.contrib.http import MultiHttpClient, RequestFailedError
        from oldman.utils.files import atomic_write

        assert self._url is not None
        # One retry covers a server that stumbles once; a wrong password or a missing file does not
        # change by asking again.
        client = MultiHttpClient(proxy_url=self._proxy_url, retry_count=1, no_retry_statuses=[401, 403, 404])
        await client.init_client()
        try:
            response = await client.get(f"{self._url}/{quote(relative)}")
        except RequestFailedError as exc:
            # Its message holds the raw address and the response body; the status is what matters.
            raise RemoteFileError(f"Could not download {self._shown(relative)}: HTTP {exc.status_code}") from None
        except Exception as exc:
            # The HTTP client's own messages may carry the address with its credentials.
            detail = self._scrub(str(exc)) or type(exc).__name__
            raise RemoteFileError(f"Could not download {self._shown(relative)}: {detail}") from None
        finally:
            await client.close_client()
        if not response.is_success:
            raise RemoteFileError(f"Could not download {self._shown(relative)}: HTTP {response.status_code}")
        atomic_write(target, response.content, follow_symlinks=False)
        self._forget(relative)

    def _module_name(self, relative: str) -> str:
        return "oldman_remote_" + hashlib.sha256(f"{self._shown_base}\0{relative}".encode()).hexdigest()[:16]

    def _forget(self, relative: str) -> None:
        self._modules.pop(relative, None)

    async def _load(self, relative: str) -> ModuleType:
        """Load a Python file once per process under a name of its own.

        It is registered in `sys.modules` like any import: without that, a file with
        `from __future__ import annotations` and a `@dataclass` fails to load. The source is
        compiled here rather than through the import system, which would write `__pycache__`
        next to it — into the cache, or into the developer's own directory — and reuse bytecode
        judged by a modification time to the second, so a file refreshed within the same second
        at the same size would keep running the old code.
        """
        module = self._modules.get(relative)
        if module is not None:
            return module
        file = await self.fetch(relative)
        if file.suffix != ".py":
            raise TypeError(f"{self._shown(relative)} is not a Python file")
        # dont_inherit: without it the file would also get this module's `from __future__ import
        # annotations`, turning its annotations into strings a normal import would not have.
        code = compile(file.read_bytes(), str(file), "exec", dont_inherit=True)
        name = self._module_name(relative)
        spec = importlib.util.spec_from_loader(name, loader=None, origin=str(file))
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        module.__file__ = str(file)
        sys.modules[name] = module
        try:
            exec(code, module.__dict__)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        self._modules[relative] = module
        return module

    def _entry(self, relative: str, wanted: Literal["run", "menu"]) -> Callable[[], Awaitable[Any]]:
        async def call() -> Any:
            module = await self._load(relative)
            shown = self._shown(relative)
            # Only functions written in the file count: `from subprocess import run` is not an entry.
            defined = [
                name for name in ("run", "menu") if inspect.isfunction(value := getattr(module, name, None)) and value.__module__ == module.__name__
            ]
            if len(defined) == 2:
                raise TypeError(f"{shown} defines both run() and menu(); a remote file does one of them")
            if defined != [wanted]:
                if defined:
                    use = "RemoteFiles.action()" if defined[0] == "run" else "RemoteFiles.menu()"
                    raise TypeError(f"{shown} defines {defined[0]}(), not {wanted}(); use {use}")
                raise TypeError(f"{shown} must define async def {wanted}()")
            function = getattr(module, wanted)
            if not inspect.iscoroutinefunction(inspect.unwrap(function)):
                raise TypeError(f"{shown}: {wanted}() must be async def")
            try:
                inspect.signature(function).bind()
            except TypeError:
                raise TypeError(f"{shown}: {wanted}() must take no arguments") from None
            return await function()

        return call


__all__ = ["Refreshed", "RemoteFileError", "RemoteFiles"]
