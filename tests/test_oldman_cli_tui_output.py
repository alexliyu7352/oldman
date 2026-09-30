"""tui output and waiting indicators: where each line goes, and what it looks like on and off a terminal."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from oldman.cli import Command, tui
from oldman.cli.service import _create_typed_command_handler
from oldman.cli.tui.output import _command_stdout


class Stream(io.TextIOWrapper):
    """A captured stream with a real encoding, which can claim to be a terminal."""

    def __init__(self, *, encoding: str = "utf-8", tty: bool = False) -> None:
        super().__init__(io.BytesIO(), encoding=encoding, write_through=True)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def getvalue(self) -> str:
        buffer = self.buffer
        assert isinstance(buffer, io.BytesIO)
        return buffer.getvalue().decode(self.encoding)


@contextmanager
def captured(*, encoding: str = "utf-8", stdout_tty: bool = False, stderr_tty: bool = False) -> Iterator[tuple[Stream, Stream]]:
    out, err = Stream(encoding=encoding, tty=stdout_tty), Stream(encoding=encoding, tty=stderr_tty)
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        yield out, err
    finally:
        sys.stdout, sys.stderr = saved


class OutputTest(unittest.TestCase):
    def test_data_and_status_lines_are_plain_text_on_their_streams(self) -> None:
        with captured() as (out, err):
            tui.echo("[bold]id[/bold]")
            tui.info("Checking [red]nginx[/red]")
            tui.success("Saved")
            tui.warning("Port 80 is taken")
            tui.error("Upload failed")

        self.assertEqual(
            ["[bold]id[/bold]", "Checking [red]nginx[/red]", "✓ Saved", "⚠ Port 80 is taken"],
            out.getvalue().splitlines(),
        )
        self.assertEqual(["✗ Upload failed"], err.getvalue().splitlines())

    def test_echo_writes_the_data_unchanged(self) -> None:
        row = "id\tname\ttrailing  \r\nbell\x07end"
        with captured() as (out, _err):
            tui.echo(row)
        self.assertEqual(row + "\n", out.getvalue())

    def test_a_stdout_closed_at_startup_takes_the_data_silently(self) -> None:
        # `command >&-` leaves sys.stdout as None; the status lines through Rich are dropped too.
        with patch.object(sys, "stdout", None):
            tui.echo("row")
            tui.info("Checking")

    def test_a_stream_that_cannot_encode_the_symbols_gets_ascii(self) -> None:
        """Ops tools run over SSH with whatever locale the server has; ✓ on latin-1 would raise."""
        with captured(encoding="latin-1") as (out, err):
            tui.success("Saved")
            tui.warning("Careful")
            tui.error("Failed")
            tui.table([["a"]], headers=["h"])
            tui.rule("next")

        text = out.getvalue()
        self.assertIn("[ok] Saved", text)
        self.assertIn("[!] Careful", text)
        self.assertEqual("[x] Failed\n", err.getvalue())

    def test_a_table_keeps_every_cell_whole(self) -> None:
        long_path = "/etc/nginx/sites-enabled/" + "segment/" * 20
        with captured() as (out, _err):
            tui.table([["[b]web[/b]", None, long_path]], headers=["Name", "Port", "Path"], title="Sites")

        lines = out.getvalue().splitlines()
        text = out.getvalue()
        self.assertIn("Sites", lines[0])
        self.assertIn("Name", text)
        self.assertIn("[b]web[/b]", text)
        self.assertNotIn("None", text)
        # Off a terminal the table is 80 columns wide; the long cell folds instead of being cut.
        self.assertLessEqual(max(len(line) for line in lines), 80)
        folded = "".join(line.split("│")[3].strip() for line in lines if line.count("│") >= 4)
        self.assertEqual(long_path, folded)

    def test_a_table_without_headers_and_a_row_too_long(self) -> None:
        with captured() as (out, _err):
            tui.table([["a", "b"], ["c"]])
        self.assertIn("a", out.getvalue())
        self.assertIn("c", out.getvalue())
        with self.assertRaisesRegex(ValueError, "3 cells but the table has 2 columns"):
            tui.table([["a", "b", "c"]], headers=["x", "y"])

    def test_a_rule_carries_its_title(self) -> None:
        with captured() as (out, _err):
            tui.rule("Nginx")
        self.assertIn(" Nginx ", out.getvalue())
        self.assertTrue(out.getvalue().startswith("─"))


class WaitingTest(unittest.TestCase):
    def test_off_a_terminal_indicators_print_plain_lines(self) -> None:
        with captured() as (out, _err):
            with tui.spinner("Downloading"):
                tui.echo("inside")
            with tui.progress("Copying", total=4) as bar:
                bar.advance()
                bar.update(completed=4, label="Copied")
            with tui.progress("Scanning") as bar:
                bar.advance(2.5)

        self.assertEqual(
            ["Downloading", "inside", "Copying", "Copied: 4/4", "Scanning", "Scanning: 2.5"],
            out.getvalue().splitlines(),
        )

    def test_an_error_inside_propagates_without_a_finished_line(self) -> None:
        with captured() as (out, _err):
            with self.assertRaises(RuntimeError), tui.progress("Copying", total=2) as bar:
                bar.advance()
                raise RuntimeError("disk full")
        self.assertEqual(["Copying"], out.getvalue().splitlines())

    def test_on_a_terminal_the_block_can_await_and_print(self) -> None:
        async def work() -> None:
            with tui.spinner("Waiting"):
                await asyncio.sleep(0.05)
                print("line while waiting")
            with tui.progress("Steps", total=2) as bar:
                await asyncio.sleep(0.05)
                bar.advance(2)

        with captured(stdout_tty=True, stderr_tty=True) as (out, _err):
            asyncio.run(work())
        self.assertIn("line while waiting", out.getvalue())
        self.assertIn("Steps", out.getvalue())

    def test_force_color_does_not_draw_an_animation_into_a_file(self) -> None:
        # Rich counts FORCE_COLOR as a terminal; the animation and the relayed data would land in the file.
        with patch.dict(os.environ, {"FORCE_COLOR": "1"}), captured() as (out, _err):
            with tui.spinner("Exporting"):
                tui.echo("a\tb")
        self.assertEqual(["Exporting", "a\tb"], out.getvalue().splitlines())


class RawStdoutTest(unittest.TestCase):
    def test_a_raw_stdout_command_keeps_stdout_for_data(self) -> None:
        with captured() as (out, err), _command_stdout(raw_stdout=True):
            tui.echo('{"id": 1}')
            tui.info("Dumping 1 record")
            tui.success("Done")
            tui.table([["a"]])
            tui.rule()
            with tui.spinner("Reading"):
                pass
            with tui.progress("Writing", total=1) as bar:
                bar.advance()

        self.assertEqual('{"id": 1}\n', out.getvalue())
        for text in ("Dumping 1 record", "✓ Done", "Reading", "Writing: 1/1"):
            self.assertIn(text, err.getvalue())

    def test_a_spinner_on_stderr_leaves_stdout_to_the_data(self) -> None:
        """Rich redirects both streams by default: the data would have gone to stderr under the spinner."""
        with captured(stderr_tty=True) as (out, err), _command_stdout(raw_stdout=True):
            with tui.spinner("Reading"):
                print('{"id": 1}')
        self.assertEqual('{"id": 1}\n', out.getvalue())
        self.assertNotIn('"id"', err.getvalue())

    def test_nested_indicators_leave_the_data_on_stdout(self) -> None:
        # Under the outer indicator sys.stderr is Rich's proxy; the inner one must still leave stdout alone.
        with captured(stderr_tty=True) as (out, _err), _command_stdout(raw_stdout=True):
            with tui.progress("Tables", total=1) as bar:
                with tui.spinner("users"):
                    tui.echo("users\t3")
                bar.advance()
        self.assertEqual("users\t3\n", out.getvalue())

    def test_the_dispatcher_routes_by_the_commands_raw_stdout(self) -> None:
        class Dump(Command):
            name = "dump"
            help = "Dump records."
            raw_stdout = True

            async def handle(self) -> None:
                tui.info("Dumping")
                tui.echo("[]")

        class Plain(Dump):
            name = "plain"
            raw_stdout = False

        class Service:
            @classmethod
            def execute_app_command(cls, command: Command, *args: Any, **kwargs: Any) -> Any:
                return asyncio.run(command.handle(*args, **kwargs))

        with captured() as (out, err):
            _create_typed_command_handler(Service, Dump())()
        self.assertEqual(("[]\n", "Dumping\n"), (out.getvalue(), err.getvalue()))
        with captured() as (out, err):
            _create_typed_command_handler(Service, Plain())()
        self.assertEqual(("Dumping\n[]\n", ""), (out.getvalue(), err.getvalue()))


if __name__ == "__main__":
    unittest.main()
