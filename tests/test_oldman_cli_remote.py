"""Remote files: local and HTTP bases, the cache and refresh, the file contract, scripts, credentials."""

from __future__ import annotations

import asyncio
import base64
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from collections.abc import Awaitable
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from oldman.cli import tui
from oldman.cli.remote import RemoteFileError, RemoteFiles


def run[T](awaitable: Awaitable[T]) -> T:
    async def main() -> T:
        return await awaitable

    return asyncio.run(main())


def write(directory: Path, relative: str, source: str) -> None:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


class FileServer:
    """Serve one directory on 127.0.0.1, optionally behind HTTP Basic authentication."""

    def __init__(self, directory: Path, *, credentials: str | None = None) -> None:
        expected = "Basic " + base64.b64encode(credentials.encode()).decode() if credentials else None

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=str(directory), **kwargs)

            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                if expected is not None and self.headers.get("Authorization") != expected:
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="remote"')
                    self.end_headers()
                    return
                if self.path.endswith("/broken.py"):
                    self.send_error(500)
                    return
                super().do_GET()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class RemoteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.served = self.root / "served"
        self.served.mkdir()
        self.cache = self.root / "cache"
        # Only the modules the remote files registered: other modules a test imported for the first time
        # (the HTTP backends, C extensions) must stay, or later tests in this process break.
        self.addCleanup(lambda: [sys.modules.pop(name) for name in list(sys.modules) if name.startswith("oldman_remote_")])

    def serve(self, *, credentials: str | None = None) -> FileServer:
        server = FileServer(self.served, credentials=credentials)
        self.addCleanup(server.stop)
        return server

    def echo_action(self, remote: RemoteFiles, path: str) -> str:
        with tui.simulate_input([]) as terminal:
            run(remote.action(path)())
        return terminal.stdout


class LocalBaseTest(RemoteTestCase):
    def test_a_local_base_is_read_in_place_and_not_cached(self) -> None:
        write(self.served, "tasks/hello.py", "async def run():\n    pass\n")
        remote = RemoteFiles(self.served, cache_dir=self.cache)
        self.assertEqual(self.served / "tasks/hello.py", run(remote.fetch("tasks/hello.py")))
        refreshed = run(remote.refresh())
        self.assertEqual(((), {}), (refreshed.updated, refreshed.failed))
        self.assertFalse(self.cache.exists())
        with self.assertRaisesRegex(FileNotFoundError, "missing.py is not a file in"):
            run(remote.fetch("missing.py"))

    def test_paths_must_stay_inside_the_base(self) -> None:
        remote = RemoteFiles(self.served, cache_dir=self.cache)
        for path in ("../outside.py", "/etc/passwd", "", "a/../../b.py", ".", "./"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                remote.action(path)
        with self.assertRaisesRegex(ValueError, "stay inside the base"):
            run(remote.fetch("../outside.py"))
        with self.assertRaisesRegex(ValueError, "no query or fragment"):
            RemoteFiles("https://example.org/files?token=1", cache_dir=self.cache)
        with self.assertRaisesRegex(ValueError, "interpreter must name"):
            remote.script("fix.sh", interpreter="")


class HttpBaseTest(RemoteTestCase):
    def test_a_file_is_downloaded_once_and_then_works_offline(self) -> None:
        write(self.served, "tasks/hello.py", "from oldman.cli import tui\n\nasync def run():\n    tui.echo('v1')\n")
        server = self.serve()
        remote = RemoteFiles(f"http://127.0.0.1:{server.port}/", cache_dir=self.cache)

        cached = run(remote.fetch("tasks/hello.py"))
        self.assertTrue(cached.is_relative_to(self.cache))
        server.stop()
        self.assertEqual(cached, run(remote.fetch("tasks/hello.py")))
        self.assertEqual("v1\n", self.echo_action(remote, "tasks/hello.py"))

    def test_refresh_downloads_again_and_the_next_run_loads_the_new_file(self) -> None:
        write(self.served, "hello.py", "from oldman.cli import tui\n\nasync def run():\n    tui.echo('v1')\n")
        write(self.served, "fix.sh", "exit 0\n")
        server = self.serve()
        remote = RemoteFiles(f"http://127.0.0.1:{server.port}", cache_dir=self.cache)
        self.assertEqual("v1\n", self.echo_action(remote, "hello.py"))
        run(remote.fetch("fix.sh"))

        write(self.served, "hello.py", "from oldman.cli import tui\n\nasync def run():\n    tui.echo('v2')\n")
        self.assertEqual("v1\n", self.echo_action(remote, "hello.py"))
        self.assertEqual(("fix.sh", "hello.py"), run(remote.refresh()).updated)
        self.assertEqual("v2\n", self.echo_action(remote, "hello.py"))

    def test_the_scheme_is_recognised_in_any_case(self) -> None:
        write(self.served, "hello.py", "async def run():\n    pass\n")
        server = self.serve()
        remote = RemoteFiles(f"HTTP://127.0.0.1:{server.port}", cache_dir=self.cache)
        self.assertTrue(run(remote.fetch("hello.py")).is_relative_to(self.cache))

    def test_refresh_skips_a_file_it_cannot_download_and_reports_it(self) -> None:
        write(self.served, "a.py", "A = 1\n")
        write(self.served, "z.py", "Z = 'old'\n")
        server = self.serve()
        remote = RemoteFiles(f"http://127.0.0.1:{server.port}", cache_dir=self.cache)
        cached_a, cached_z = run(remote.fetch("a.py")), run(remote.fetch("z.py"))

        (self.served / "a.py").unlink()
        write(self.served, "z.py", "Z = 'new'\n")
        refreshed = run(remote.refresh())

        self.assertEqual(("z.py",), refreshed.updated)
        self.assertEqual({"a.py": f"Could not download http://127.0.0.1:{server.port}/a.py: HTTP 404"}, refreshed.failed)
        self.assertEqual("Z = 'new'\n", cached_z.read_text())
        # The file the base no longer has stays cached, so the tool keeps working offline.
        self.assertEqual("A = 1\n", cached_a.read_text())

    def test_each_base_address_has_its_own_cache_and_modules(self) -> None:
        for tag in ("v1", "v2"):
            write(self.served, f"{tag}/hello.py", f"from oldman.cli import tui\n\nasync def run():\n    tui.echo({tag!r})\n")
        server = self.serve()
        first = RemoteFiles(f"http://127.0.0.1:{server.port}/v1", cache_dir=self.cache)
        second = RemoteFiles(f"http://127.0.0.1:{server.port}/v2", cache_dir=self.cache)
        self.assertEqual("v1\n", self.echo_action(first, "hello.py"))
        self.assertEqual("v2\n", self.echo_action(second, "hello.py"))
        self.assertNotEqual(run(first.fetch("hello.py")).parent, run(second.fetch("hello.py")).parent)

    def test_credentials_in_the_address_authenticate_and_never_show(self) -> None:
        write(self.served, "hello.py", "async def run():\n    pass\n")
        server = self.serve(credentials="ops:s3cret:pass")
        # ":" in a password is written %3A; the HTTP client may show either form.
        remote = RemoteFiles(f"http://ops:s3cret%3Apass@127.0.0.1:{server.port}/", cache_dir=self.cache)
        run(remote.fetch("hello.py"))

        with self.assertRaises(RemoteFileError) as missing:
            run(remote.fetch("missing.py"))
        self.assertEqual(f"Could not download http://127.0.0.1:{server.port}/missing.py: HTTP 404", str(missing.exception))

        # A 500 is retried, and the HTTP client's final error quotes the raw address.
        with self.assertRaises(RemoteFileError) as broken:
            run(remote.fetch("broken.py"))
        self.assertEqual(f"Could not download http://127.0.0.1:{server.port}/broken.py: HTTP 500", str(broken.exception))

        wrong = RemoteFiles(f"http://ops:wrong-pass@127.0.0.1:{server.port}/", cache_dir=self.cache)
        with self.assertRaisesRegex(RemoteFileError, "HTTP 401") as refused:
            run(wrong.fetch("other.py"))
        self.assertNotIn("wrong-pass", str(refused.exception))

        server.stop()
        with self.assertRaises(RemoteFileError) as unreachable:
            run(remote.fetch("other.py"))
        self.assertNotIn("s3cret", str(unreachable.exception))
        self.assertIn(f"http://127.0.0.1:{server.port}/other.py", str(unreachable.exception))

    def test_every_written_form_of_the_password_is_scrubbed(self) -> None:
        # Typed with a lower-case escape; an HTTP client re-quoting it writes %3A.
        remote = RemoteFiles("https://ops:s3cret%3apass@files.example.org/ops", cache_dir=self.cache)
        for leaked in ("https://ops:s3cret%3apass@files.example.org/x", "decoded s3cret:pass", "re-quoted s3cret%3Apass"):
            with self.subTest(leaked=leaked):
                self.assertNotIn("s3cret", remote._scrub(leaked))


class FileContractTest(RemoteTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.remote = RemoteFiles(self.served, cache_dir=self.cache)

    def test_a_menu_file_becomes_a_submenu_of_the_tool_menu(self) -> None:
        write(
            self.served,
            "nginx.py",
            """
            from __future__ import annotations

            from dataclasses import dataclass

            from oldman.cli import tui


            @dataclass
            class Site:
                name: str


            async def reload() -> None:
                tui.echo(f"reloaded {Site('example.org').name}")


            async def menu() -> tui.Menu:
                return tui.Menu("Nginx", [tui.Item("Reload", action=reload)])
            """,
        )
        tool_menu = tui.Menu("Tool", [tui.Item("Nginx", load=self.remote.menu("nginx.py"))])
        with tui.simulate_input(["1", "1", "0", "0"]) as terminal:
            run(tui.run_menu(tool_menu))
        self.assertIn("reloaded example.org\n", terminal.stdout)
        self.assertIn(" 1. Reload\n", terminal.stdout)

    def test_a_file_defines_one_async_entry_without_arguments(self) -> None:
        cases = {
            "nothing.py": ("x = 1\n", "action", r"must define async def run\(\)"),
            "both.py": ("async def run():\n    pass\n\nasync def menu():\n    pass\n", "action", r"defines both run\(\) and menu\(\)"),
            "sync.py": ("def run():\n    pass\n", "action", r"run\(\) must be async def"),
            "arguments.py": ("async def run(days):\n    pass\n", "action", r"run\(\) must take no arguments"),
            "a_menu.py": ("async def menu():\n    pass\n", "action", r"defines menu\(\), not run\(\); use RemoteFiles.menu\(\)"),
            "a_task.py": ("async def run():\n    pass\n", "menu", r"defines run\(\), not menu\(\); use RemoteFiles.action\(\)"),
            "not_a_menu.py": ("async def menu():\n    return ['Reload']\n", "menu", r"menu\(\) returned list, not tui.Menu"),
        }
        for name, (source, kind, message) in cases.items():
            write(self.served, name, source)
            with self.subTest(name=name), self.assertRaisesRegex(TypeError, message):
                run(getattr(self.remote, kind)(name)())

    def test_a_file_runs_with_its_own_future_imports_only(self) -> None:
        # No `from __future__ import annotations` here: annotations stay objects, as in a normal import,
        # and a structure may refer to a type defined in the same function.
        write(
            self.served,
            "plain.py",
            """
            import msgspec

            from oldman.cli import tui


            def decode():
                class Point(msgspec.Struct):
                    x: int

                class Line(msgspec.Struct):
                    start: Point

                return msgspec.json.decode(b'{"start": {"x": 1}}', type=Line)


            def scale(x: int) -> int:
                return x


            async def run():
                tui.echo(f"{scale.__annotations__['x'].__name__} {decode().start.x}")
            """,
        )
        self.assertEqual("int 1\n", self.echo_action(self.remote, "plain.py"))

    def test_an_imported_function_named_run_is_not_an_entry(self) -> None:
        write(
            self.served,
            "status.py",
            """
            from subprocess import run

            from oldman.cli import tui


            async def menu() -> tui.Menu:
                return tui.Menu("Status", [tui.Item("Show", action=menu)])
            """,
        )
        self.assertIsInstance(run(self.remote.menu("status.py")()), tui.Menu)


class ScriptTest(RemoteTestCase):
    def test_a_script_runs_with_its_arguments_and_exit_status(self) -> None:
        write(
            self.served,
            "record.py",
            """
            import sys
            from pathlib import Path

            Path(sys.argv[1]).write_text(" ".join(sys.argv[2:]))
            sys.exit(int(sys.argv[2]))
            """,
        )
        output = self.root / "arguments.txt"
        remote = RemoteFiles(self.served, cache_dir=self.cache)

        run(remote.script("record.py", str(output), "0", "extra words", interpreter=sys.executable)())
        self.assertEqual("0 extra words", output.read_text())

        with self.assertRaises(subprocess.CalledProcessError) as failed:
            run(remote.script("record.py", str(output), "3", interpreter=sys.executable)())
        self.assertEqual(3, failed.exception.returncode)
        self.assertEqual([sys.executable, "record.py", str(output), "3"], failed.exception.cmd)

        run(remote.script("record.py", str(output), "4", interpreter=sys.executable, check=False)())
        self.assertEqual("4", output.read_text())


if __name__ == "__main__":
    unittest.main()
