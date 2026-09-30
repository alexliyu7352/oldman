"""tui questions: answers, re-asking, cancelling, and what happens when input is not a terminal."""

from __future__ import annotations

import asyncio
import enum
import io
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch

import typer

from oldman.cli import Command, tui
from oldman.cli.service import _create_typed_command_handler
from oldman.cli.tui.output import _command_stdout
from tests.tui_support import TerminalStream, without_preset_answers

ROOT = Path(__file__).resolve().parents[1]


def setUpModule() -> None:
    unittest.enterModuleContext(without_preset_answers())


@contextmanager
def no_terminal() -> Iterator[io.StringIO]:
    """stdin that is not a terminal (a test run from a shell has a real one), with output captured."""
    output = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO("typed but never read\n")
    try:
        with redirect_stdout(output), redirect_stderr(output):
            yield output
    finally:
        sys.stdin = saved


class Shape(enum.Enum):
    ROUND = "round"
    SQUARE = "square"


class SimulatedInputTest(unittest.TestCase):
    def test_simulated_answers_count_as_a_terminal_and_are_shown_like_one(self) -> None:
        saved = sys.stdin
        sys.stdin = io.StringIO()
        try:
            with tui.simulate_input(["web01"]) as terminal:
                self.assertEqual("web01", tui.ask("Host"))
        finally:
            sys.stdin = saved
        self.assertEqual("Host: web01\n", terminal.stdout)
        self.assertEqual([], terminal.remaining)

    def test_running_out_of_answers_names_the_prompt(self) -> None:
        """A test must never fall through to the real terminal and hang."""
        with self.assertRaisesRegex(RuntimeError, "ran out of answers at the prompt 'Port: '"), tui.simulate_input([]):
            tui.ask("Port")

    def test_ctrl_c_and_end_of_input_cancel_with_their_reason(self) -> None:
        for answer, reason in ((KeyboardInterrupt, "interrupt"), (EOFError, "end-of-input")):
            with self.subTest(reason=reason), tui.simulate_input([answer]):
                with self.assertRaises(tui.Cancelled) as caught:
                    tui.ask("Host")
                self.assertEqual(reason, caught.exception.reason)


class CtrlCInsideAnEventLoopTest(unittest.TestCase):
    def test_a_blocking_read_inside_asyncio_run_is_interrupted_by_ctrl_c(self) -> None:
        """asyncio.run turns the first Ctrl-C into cancelling its main task, which a blocking read never
        notices: the prompt stayed and the cancellation landed at the next await. While reading, Ctrl-C
        must raise KeyboardInterrupt as it does outside an event loop."""
        from oldman.cli.tui import inputs

        handlers: list[object] = []

        def fake_input(prompt: str = "") -> str:
            handlers.append(signal.getsignal(signal.SIGINT))
            return "web01"

        async def command() -> tuple[str, object]:
            with patch.object(inputs, "_interactive", return_value=True), patch("builtins.input", fake_input):
                answer = tui.ask("Host")
            return answer, signal.getsignal(signal.SIGINT)

        with redirect_stdout(io.StringIO()):
            answer, after = asyncio.run(command())
        self.assertEqual("web01", answer)
        self.assertIs(signal.default_int_handler, handlers[0])
        # The runner's own handler is back once the read is over.
        self.assertIsNot(signal.default_int_handler, after)


class RealTerminalTest(unittest.TestCase):
    def test_the_prompt_shows_on_the_terminal_with_stderr_redirected(self) -> None:
        """Without readline, input(prompt) writes the prompt to stderr: `command 2>err.log` hid it."""
        master, slave = pty.openpty()
        with tempfile.TemporaryFile() as errors:
            child = subprocess.Popen(
                [sys.executable, "-c", "from oldman.cli import tui; print('GOT', tui.ask('Port'))"],
                stdin=slave,
                stdout=slave,
                stderr=errors,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
            )
            os.close(slave)
            screen = b""
            try:
                screen = _read_until(master, b"Port: ", screen)
                os.write(master, b"22\n")
                screen = _read_until(master, b"GOT 22", screen)
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
                os.close(master)
            errors.seek(0)
            self.assertEqual(b"", errors.read())
        self.assertIn(b"Port: ", screen)


def _read_until(master: int, expected: bytes, screen: bytes) -> bytes:
    deadline = time.monotonic() + 10
    while expected not in screen:
        if time.monotonic() > deadline:
            raise AssertionError(f"{expected!r} not shown; the terminal had {screen!r}")
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
            screen += os.read(master, 1024)
    return screen


class AskTest(unittest.TestCase):
    def test_an_empty_answer(self) -> None:
        with tui.simulate_input(["", "", "", "", "app"]) as terminal:
            self.assertEqual("8080", tui.ask("Port", default="8080"))
            self.assertEqual("", tui.ask("Email", default=""))
            self.assertIsNone(tui.ask("Comment", required=False))
            self.assertEqual("app", tui.ask("Name"))
        self.assertIn("Port [8080]: ", terminal.stdout)
        self.assertIn("Email: ", terminal.stdout)
        self.assertEqual(1, terminal.stdout.count("⚠ This value is required."))

    def test_conversion_choices_and_validation_ask_again_with_the_reason(self) -> None:
        def even(value: int) -> None:
            if value % 2:
                raise ValueError("Pick an even number.")

        def strict(text: str) -> str:
            raise ValueError("")

        with tui.simulate_input(["x", "3", "4", "1.5x", "2.5", "?"]) as terminal:
            self.assertEqual(4, tui.ask("Workers", type=int, choices=[2, 4], validate=even))
            self.assertEqual(2.5, tui.ask("Ratio", type=float))
            with self.assertRaisesRegex(RuntimeError, "ran out"):
                tui.ask("Code", type=strict)

        lines = terminal.stdout.splitlines()
        self.assertIn("Workers (2/4): x", lines)
        self.assertIn("⚠ Enter a whole number.", lines)
        # choices are compared with the converted value: "3" became 3, which is not 2 or 4.
        self.assertIn("⚠ Choose one of: 2, 4", lines)
        self.assertIn("⚠ Enter a number.", lines)
        # A converter's ValueError without a message gets the generic text, not "Invalid value: ".
        self.assertIn("⚠ Invalid value.", lines)

    def test_validate_rejects_with_its_own_message(self) -> None:
        def free_port(value: int) -> None:
            if value < 1024:
                raise ValueError("Ports below 1024 need root.")

        with tui.simulate_input(["80", "8080"]) as terminal:
            self.assertEqual(8080, tui.ask("Port", type=int, validate=free_port))
        self.assertIn("⚠ Ports below 1024 need root.", terminal.stdout)

    def test_a_secret_is_hidden_kept_as_typed_and_confirmed(self) -> None:
        with tui.simulate_input([" pa ss", "other", " pa ss", " pa ss"]) as terminal:
            self.assertEqual(" pa ss", tui.ask("Password", secret=True, confirm_secret=True, help="At least 12 characters."))
        self.assertNotIn("pa ss", terminal.stdout)
        self.assertEqual(2, terminal.stdout.count("Confirm Password: "))
        self.assertEqual(1, terminal.stdout.count("⚠ The two entries do not match."))
        self.assertTrue(terminal.stdout.startswith("At least 12 characters.\n"))

    def test_without_a_terminal_a_default_is_taken_and_a_missing_one_is_an_error(self) -> None:
        with no_terminal() as output:
            self.assertEqual("8080", tui.ask("Port", default="8080"))
            self.assertEqual("hunter2", tui.ask("Password", default="hunter2", secret=True))
            self.assertIsNone(tui.ask("Comment", required=False))
            with self.assertRaisesRegex(tui.NotInteractive, "Name needs an answer, but stdin and the output are not both terminals."):
                tui.ask("Name")
        self.assertEqual("Port: 8080\nPassword: ***\n", output.getvalue())

    def test_questions_need_their_output_on_a_terminal_too(self) -> None:
        # A program that runs the command and captures its output, or `command > out.txt`: the
        # questions would go there while the command waited on the terminal.
        captured = io.StringIO()
        with patch.object(sys, "stdin", TerminalStream("typed\n")), redirect_stdout(captured):
            self.assertEqual("8080", tui.ask("Port", default="8080"))
            with self.assertRaises(tui.NotInteractive):
                tui.ask("Name")
        self.assertEqual("Port: 8080\n", captured.getvalue())

    def test_a_raw_stdout_command_still_asks_with_its_data_redirected(self) -> None:
        data = io.StringIO()
        screen = TerminalStream()
        with (
            patch.object(sys, "stdin", TerminalStream("users\n")),
            redirect_stdout(data),
            redirect_stderr(screen),
            _command_stdout(raw_stdout=True),
        ):
            self.assertEqual("users", tui.ask("Table"))
        self.assertEqual("", data.getvalue())
        self.assertIn("Table: ", screen.getvalue())

    def test_a_stdin_closed_at_startup_is_not_a_terminal(self) -> None:
        # `python app.py 0<&-` leaves sys.stdin as None.
        output = io.StringIO()
        with patch.object(sys, "stdin", None), redirect_stdout(output), redirect_stderr(output):
            self.assertTrue(tui.confirm("Go on", default=True))
            with self.assertRaises(tui.NotInteractive):
                tui.ask("Name")


class ConfirmTest(unittest.TestCase):
    def test_answers_default_and_asking_again(self) -> None:
        with tui.simulate_input(["", "YES", "maybe", "n"]) as terminal:
            self.assertTrue(tui.confirm("Restart nginx?", default=True))
            self.assertTrue(tui.confirm("Reload?"))
            self.assertFalse(tui.confirm("Delete?"))
        self.assertIn("Restart nginx? [Y/n]: ", terminal.stdout)
        self.assertIn("Delete? [y/N]: maybe", terminal.stdout)
        self.assertIn("⚠ Answer yes or no.", terminal.stdout)

    def test_assume_yes_and_no_terminal(self) -> None:
        with no_terminal() as output:
            self.assertTrue(tui.confirm("Delete?", assume_yes=True))
            self.assertFalse(tui.confirm("Delete?"))
            self.assertTrue(tui.confirm("Continue?", default=True))
        self.assertEqual("Delete?: yes\nDelete?: no\nContinue?: yes\n", output.getvalue())


class ChooseTest(unittest.TestCase):
    def test_a_number_a_value_a_text_or_what_match_resolves(self) -> None:
        languages = [("en", "English"), ("zh-Hans", "简体中文")]

        def alias(answer: str) -> str | None:
            return "zh-Hans" if answer.lower() in {"zh", "zh-cn"} else None

        with tui.simulate_input(["2", "EN", "简体中文", "zh-cn", "", "square"]) as terminal:
            self.assertEqual("zh-Hans", tui.choose("Language", languages))
            self.assertEqual("en", tui.choose("Language", languages))
            self.assertEqual("zh-Hans", tui.choose("Language", languages))
            self.assertEqual("zh-Hans", tui.choose("Language", languages, match=alias))
            self.assertEqual("en", tui.choose("Language", languages, default="en"))
            self.assertIs(Shape.SQUARE, tui.choose("Shape", list(Shape)))
        self.assertIn("1. English\n2. 简体中文\n: 2", terminal.stdout)
        self.assertIn("[1]: ", terminal.stdout)
        self.assertIn("1. round\n2. square", terminal.stdout)

    def test_an_option_whose_text_is_a_number_is_chosen_by_that_text(self) -> None:
        with tui.simulate_input(["1", "2"]):
            self.assertEqual("1", tui.choose("Port", ["3", "1"]))
            self.assertEqual("1", tui.choose("Port", ["3", "1"]))
        with patch.dict(os.environ, {"OLDMAN_ANSWER_PORT": "1", "OLDMAN_ANSWER_PORTS": "1"}), tui.simulate_input([]):
            self.assertEqual("1", tui.choose("Port", ["3", "1"], key="port"))
            self.assertEqual(["1"], tui.choose_many("Ports", ["3", "1"], key="ports"))

    def test_a_typed_number_is_the_entry_even_when_a_hidden_value_is_that_number(self) -> None:
        users = [(17, "alice"), (3, "bob"), (1, "carol")]
        with tui.simulate_input(["1", "carol", "17"]):
            self.assertEqual(17, tui.choose("Delete which user", users))
            self.assertEqual(1, tui.choose("Delete which user", users))
            self.assertEqual(17, tui.choose("Delete which user", users))
        with patch.dict(os.environ, {"OLDMAN_ANSWER_USER": "1", "OLDMAN_ANSWER_USERS": "1 3"}), tui.simulate_input(["1 3"]):
            # A preset is written with the values.
            self.assertEqual(1, tui.choose("Delete which user", users, key="user"))
            self.assertEqual([1, 3], tui.choose_many("Delete which users", users, key="users"))
            self.assertEqual([17, 1], tui.choose_many("Delete which users", users))

    def test_an_answer_that_fits_nothing_asks_again(self) -> None:
        with tui.simulate_input(["3", "fr", "1"]) as terminal:
            self.assertEqual("en", tui.choose("Language", ["en", "de"]))
            with self.assertRaisesRegex(RuntimeError, "ran out"):
                tui.choose("Language", ["en", "de"], invalid="Invalid selection / 无效选择")
        self.assertEqual(2, terminal.stdout.count("⚠ Enter a number from 1 to 2."))
        self.assertEqual(0, terminal.stdout.count("无效选择"))

    def test_the_callers_invalid_message(self) -> None:
        with tui.simulate_input(["fr", "de"]) as terminal:
            self.assertEqual("de", tui.choose("Language", ["en", "de"], invalid="Invalid selection / 无效选择"))
        self.assertIn("⚠ Invalid selection / 无效选择", terminal.stdout)

    def test_a_default_must_be_an_option_and_no_terminal_takes_it(self) -> None:
        with self.assertRaisesRegex(ValueError, "default 'fr' is not one of the options"):
            tui.choose("Language", ["en", "de"], default="fr")
        with self.assertRaisesRegex(ValueError, "at least one option"):
            tui.choose("Language", [])
        with no_terminal() as output:
            self.assertEqual("de", tui.choose("Language", [("en", "English"), ("de", "Deutsch")], default="de"))
            with self.assertRaises(tui.NotInteractive):
                tui.choose("Language", ["en", "de"])
        self.assertEqual("Language: Deutsch\n", output.getvalue())


class ChooseManyTest(unittest.TestCase):
    def test_several_answers_duplicates_and_a_wrong_one(self) -> None:
        units = ["nginx", "sshd", "cron"]
        with tui.simulate_input(["1, cron 1", "2 nope", "sshd", ""]) as terminal:
            self.assertEqual(["nginx", "cron"], tui.choose_many("Units", units))
            self.assertEqual(["sshd"], tui.choose_many("Units", units))
            self.assertEqual(["cron"], tui.choose_many("Units", units, default=["cron"]))
        self.assertIn("⚠ Not in the list: nope", terminal.stdout)
        self.assertIn("3. cron\n[3]: ", terminal.stdout)
        with self.assertRaisesRegex(ValueError, "default 'x'"):
            tui.choose_many("Units", units, default=["x"])
        with no_terminal() as output:
            self.assertEqual(["sshd"], tui.choose_many("Units", units, default=["sshd"]))
        self.assertEqual("Units: sshd\n", output.getvalue())


class PresetAnswerTest(unittest.TestCase):
    def test_a_preset_answer_is_used_without_asking_even_in_a_terminal(self) -> None:
        environment = {"OLDMAN_ANSWER_SITE_PORT": " 8080 ", "OLDMAN_ANSWER_SITE_PASSWORD": " s3 "}
        with patch.dict(os.environ, environment), tui.simulate_input([]) as terminal:
            self.assertEqual(8080, tui.ask("Port", type=int, key="site.port"))
            self.assertEqual(" s3 ", tui.ask("Password", secret=True, confirm_secret=True, key="site.password"))
        self.assertEqual("Port: 8080 (OLDMAN_ANSWER_SITE_PORT)\nPassword: *** (OLDMAN_ANSWER_SITE_PASSWORD)\n", terminal.stdout)

    def test_an_empty_preset_answer_follows_the_empty_answer_rule(self) -> None:
        with patch.dict(os.environ, {"OLDMAN_ANSWER_A": "", "OLDMAN_ANSWER_B": "", "OLDMAN_ANSWER_C": ""}), tui.simulate_input([]):
            self.assertEqual("8000", tui.ask("A", default="8000", key="a"))
            self.assertIsNone(tui.ask("B", required=False, key="b"))
            with self.assertRaisesRegex(ValueError, "OLDMAN_ANSWER_C is not valid: This value is required."):
                tui.ask("C", key="c")

    def test_a_preset_answer_that_does_not_fit_is_an_error_not_a_question(self) -> None:
        def unprivileged(port: int) -> None:
            if port < 1024:
                raise ValueError("Ports below 1024 need root.")

        with patch.dict(os.environ, {"OLDMAN_ANSWER_PORT": "80"}), tui.simulate_input([]):
            with self.assertRaisesRegex(ValueError, "OLDMAN_ANSWER_PORT is not valid: Ports below 1024 need root."):
                tui.ask("Port", type=int, validate=unprivileged, key="port")

    def test_without_a_terminal_the_error_names_the_variable_to_set(self) -> None:
        with (
            no_terminal(),
            self.assertRaisesRegex(tui.NotInteractive, "Name needs an answer: run it in a terminal or set OLDMAN_ANSWER_STARTAPP_DISPLAY_NAME."),
        ):
            tui.ask("Name", key="startapp.display_name")

    def test_confirm(self) -> None:
        environment = {"OLDMAN_ANSWER_R1": "no", "OLDMAN_ANSWER_R2": "1", "OLDMAN_ANSWER_R3": "", "OLDMAN_ANSWER_R4": "sure"}
        with patch.dict(os.environ, environment), tui.simulate_input([]) as terminal:
            self.assertFalse(tui.confirm("Restart?", default=True, key="r1"))
            self.assertTrue(tui.confirm("Restart?", key="r2"))
            self.assertTrue(tui.confirm("Restart?", default=True, key="r3"))
            self.assertTrue(tui.confirm("Restart?", assume_yes=True, key="r1"))  # --yes wins over a preset
            with self.assertRaisesRegex(ValueError, "OLDMAN_ANSWER_R4 must be true or false, not 'sure'"):
                tui.confirm("Restart?", key="r4")
        self.assertIn("Restart?: no (OLDMAN_ANSWER_R1)", terminal.stdout)

    def test_choose_and_choose_many(self) -> None:
        languages = [("en", "English"), ("zh-Hans", "简体中文")]
        environment = {
            "OLDMAN_ANSWER_L1": "2",
            "OLDMAN_ANSWER_L2": "english",
            "OLDMAN_ANSWER_L3": "zh",
            "OLDMAN_ANSWER_L4": "",
            "OLDMAN_ANSWER_L5": "fr",
            "OLDMAN_ANSWER_U1": "nginx, 3",
            "OLDMAN_ANSWER_U2": "",
            "OLDMAN_ANSWER_U3": "nginx apache",
        }
        units = ["nginx", "sshd", "cron"]
        with patch.dict(os.environ, environment), tui.simulate_input([]) as terminal:
            self.assertEqual("zh-Hans", tui.choose("Language", languages, key="l1"))
            self.assertEqual("en", tui.choose("Language", languages, key="l2"))
            self.assertEqual("zh-Hans", tui.choose("Language", languages, match=lambda a: "zh-Hans" if a == "zh" else None, key="l3"))
            self.assertEqual("en", tui.choose("Language", languages, default="en", key="l4"))
            with self.assertRaisesRegex(ValueError, "OLDMAN_ANSWER_L5 must be one of: English, 简体中文"):
                tui.choose("Language", languages, key="l5")
            self.assertEqual(["nginx", "cron"], tui.choose_many("Units", units, key="u1"))
            self.assertEqual(["sshd"], tui.choose_many("Units", units, default=["sshd"], key="u2"))
            with self.assertRaisesRegex(ValueError, "OLDMAN_ANSWER_U3 must be one of: nginx, sshd, cron"):
                tui.choose_many("Units", units, key="u3")
        self.assertIn("Language: 简体中文 (OLDMAN_ANSWER_L1)", terminal.stdout)
        self.assertIn("Units: nginx, cron (OLDMAN_ANSWER_U1)", terminal.stdout)

    def test_choose_validate_asks_again_but_rejects_a_preset(self) -> None:
        def with_database(database: str) -> None:
            if database == "none":
                raise ValueError("Dashboard projects require a database.")

        with tui.simulate_input(["none", "sqlite"]) as terminal:
            self.assertEqual("sqlite", tui.choose("Database", ["none", "sqlite"], validate=with_database))
        self.assertIn("⚠ Dashboard projects require a database.", terminal.stdout)
        with patch.dict(os.environ, {"OLDMAN_ANSWER_DB": "none"}), tui.simulate_input([]):
            with self.assertRaisesRegex(ValueError, "OLDMAN_ANSWER_DB is not valid: Dashboard projects require a database."):
                tui.choose("Database", ["none", "sqlite"], validate=with_database, key="db")

    def test_the_variable_name(self) -> None:
        self.assertEqual("OLDMAN_ANSWER_STARTPROJECT_TYPE", tui.answer_variable("startproject.type"))
        self.assertEqual("OLDMAN_ANSWER_ADD_SITE_PORT", tui.answer_variable("add-site.port"))
        for key in ("", ".type", "site port"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "question key"):
                tui.answer_variable(key)


class CommandTest(unittest.TestCase):
    def test_prompts_of_a_raw_stdout_command_stay_off_stdout(self) -> None:
        with tui.simulate_input(["users"]) as terminal, _command_stdout(raw_stdout=True):
            table = tui.ask("Table")
            tui.echo(f'{{"table": "{table}"}}')
        self.assertEqual('{"table": "users"}\n', terminal.stdout)
        self.assertEqual("Table: users\n", terminal.stderr)

    def test_the_dispatcher_reports_cancelling_and_missing_input(self) -> None:
        class Ask(Command):
            name = "ask"
            help = "Ask one question."

            async def handle(self) -> None:
                tui.ask("Name")

        class Service:
            @classmethod
            def execute_app_command(cls, command: Command, *args: Any, **kwargs: Any) -> Any:
                return asyncio.run(command.handle(*args, **kwargs))

        handler = _create_typed_command_handler(Service, Ask())
        with tui.simulate_input([KeyboardInterrupt]) as terminal, self.assertRaises(typer.Exit) as exited:
            handler()
        self.assertEqual(1, exited.exception.exit_code)
        self.assertIn("✗ Aborted.", terminal.stderr)
        self.assertNotIn("Error executing command", terminal.stderr)

        with no_terminal() as output, self.assertRaises(typer.Exit):
            handler()
        self.assertIn("Error: Name needs an answer, but stdin and the output are not both terminals.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
