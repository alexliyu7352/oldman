"""tui forms (terminal, environment, remembered answers) and menus (actions, submenus, loading, leaving)."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import tempfile
import unittest
from collections.abc import Coroutine
from pathlib import Path
from typing import Any
from unittest.mock import patch

from oldman.cli import tui
from tests.tui_support import without_preset_answers


def setUpModule() -> None:
    unittest.enterModuleContext(without_preset_answers())


def run(coroutine: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coroutine)


class AskFormTest(unittest.TestCase):
    def fields(self) -> list[tui.Field]:
        return [
            tui.Field("domain", "Domain"),
            tui.Field("port", "Port", type=int, default=8000),
            tui.Field("ssl", "Enable TLS", type=bool, default=True),
            tui.Field("engine", "Engine", choices=["nginx", "openresty"], default="nginx"),
            tui.Field("admin-password", "Admin password", secret=True),
        ]

    def test_the_fields_are_asked_in_order(self) -> None:
        with tui.simulate_input(["example.org", "", "n", "openresty", "pw"]) as terminal:
            answers = tui.ask_form(self.fields())
        self.assertEqual(
            {"domain": "example.org", "port": 8000, "ssl": False, "engine": "openresty", "admin-password": "pw"},
            answers,
        )
        self.assertIn("Enable TLS [Y/n]: n", terminal.stdout)
        self.assertIn("Engine (nginx/openresty) [nginx]: openresty", terminal.stdout)

    def test_preset_answers_are_used_without_asking(self) -> None:
        environment = {
            "OLDMAN_ANSWER_OPS_DOMAIN": "example.org",
            "OLDMAN_ANSWER_OPS_PORT": "9000",
            "OLDMAN_ANSWER_OPS_SSL": "no",
            "OLDMAN_ANSWER_OPS_ADMIN_PASSWORD": "pw",
        }
        with patch.dict(os.environ, environment), tui.simulate_input(["openresty"]) as terminal:
            answers = tui.ask_form(self.fields(), key_prefix="ops")
        self.assertEqual(
            {"domain": "example.org", "port": 9000, "ssl": False, "engine": "openresty", "admin-password": "pw"},
            answers,
        )
        self.assertIn("Port: 9000 (OLDMAN_ANSWER_OPS_PORT)", terminal.stdout)
        self.assertIn("Enable TLS: no (OLDMAN_ANSWER_OPS_SSL)", terminal.stdout)
        self.assertIn("Admin password: *** (OLDMAN_ANSWER_OPS_ADMIN_PASSWORD)", terminal.stdout)
        self.assertNotIn("pw", terminal.stdout)
        self.assertEqual([], terminal.remaining)

    def test_a_preset_answer_that_does_not_fit_is_an_error_naming_the_variable(self) -> None:
        cases = {
            "OLDMAN_ANSWER_OPS_PORT": ("eighty", "OLDMAN_ANSWER_OPS_PORT is not valid: Enter a whole number."),
            "OLDMAN_ANSWER_OPS_SSL": ("maybe", "OLDMAN_ANSWER_OPS_SSL must be true or false, not 'maybe'"),
            "OLDMAN_ANSWER_OPS_ENGINE": ("apache", "OLDMAN_ANSWER_OPS_ENGINE is not valid: Choose one of: nginx, openresty"),
        }
        for variable, (value, message) in cases.items():
            with self.subTest(variable=variable), patch.dict(os.environ, {"OLDMAN_ANSWER_OPS_DOMAIN": "x", variable: value}):
                with self.assertRaisesRegex(ValueError, message), tui.simulate_input(["", "", "", "", "pw"]):
                    tui.ask_form(self.fields(), key_prefix="ops")

    def test_a_key_that_cannot_name_a_variable_fails_before_any_question(self) -> None:
        with self.assertRaisesRegex(ValueError, "question key 'site port.port'"), tui.simulate_input([]):
            tui.ask_form([tui.Field("port", "Port")], key_prefix="site port")

    def test_remembered_answers_are_next_times_defaults_and_secrets_are_not_kept(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(json.dumps({"unrelated": 1}))
            fields = [*self.fields(), tui.Field("root", "Root", type=Path, default=Path("/srv"))]
            with tui.simulate_input(["example.org", "9000", "n", "openresty", "pw", ""]):
                tui.ask_form(fields, remember=path)
            saved = json.loads(path.read_text())
            self.assertEqual(
                {"unrelated": 1, "domain": "example.org", "port": 9000, "ssl": False, "engine": "openresty"},
                saved,
            )

            with tui.simulate_input(["", "", "", "", "pw2", ""]) as terminal:
                again = tui.ask_form(fields, remember=path)
            self.assertEqual(("example.org", 9000, False, "openresty"), (again["domain"], again["port"], again["ssl"], again["engine"]))
            self.assertIn("Domain [example.org]: ", terminal.stdout)
            self.assertIn("Enable TLS [y/N]: ", terminal.stdout)

    def test_a_remembered_answer_that_no_longer_fits_is_not_offered(self) -> None:
        def unprivileged(port: int) -> None:
            if port < 1024:
                raise ValueError("Ports below 1024 need root.")

        fields = [
            tui.Field("domain", "Domain"),
            tui.Field("port", "Port", type=int, default=8000, validate=unprivileged),
            tui.Field("ssl", "Enable TLS", type=bool, default=True),
            tui.Field("engine", "Engine", choices=["nginx", "openresty"], default="nginx"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(json.dumps({"domain": "example.org", "port": 80, "ssl": "no", "engine": "apache"}))
            with tui.simulate_input(["", "", "", ""]) as terminal:
                answers = tui.ask_form(fields, remember=path)
        self.assertEqual({"domain": "example.org", "port": 8000, "ssl": True, "engine": "nginx"}, answers)
        self.assertIn("⚠ Ignoring the saved answer for Port: Ports below 1024 need root.", terminal.stdout)
        self.assertIn("⚠ Ignoring the saved answer for Enable TLS: Answer yes or no.", terminal.stdout)
        self.assertIn("⚠ Ignoring the saved answer for Engine: Choose one of: nginx, openresty", terminal.stdout)

    def test_an_empty_remembered_answer_does_not_skip_required_and_a_preset_skips_the_check(self) -> None:
        def unprivileged(port: int) -> None:
            if port < 1024:
                raise ValueError("Ports below 1024 need root.")

        fields = [tui.Field("domain", "Domain"), tui.Field("port", "Port", type=int, default=8000, validate=unprivileged)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(json.dumps({"domain": "", "port": 80}))
            with patch.dict(os.environ, {"OLDMAN_ANSWER_SITE_PORT": "9000"}), tui.simulate_input(["", "example.org"]) as terminal:
                answers = tui.ask_form(fields, key_prefix="site", remember=path)
        self.assertEqual({"domain": "example.org", "port": 9000}, answers)
        self.assertIn("⚠ Ignoring the saved answer for Domain: This value is required.", terminal.stdout)
        self.assertNotIn("saved answer for Port", terminal.stdout)

    def test_an_unreadable_answers_file_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            for content in ("{broken", "[1, 2]"):
                path.write_text(content)
                with self.subTest(content=content), tui.simulate_input(["example.org"]) as terminal:
                    self.assertEqual({"domain": "example.org"}, tui.ask_form([tui.Field("domain", "Domain")], remember=path))
                self.assertIn("⚠ Ignoring the saved answers in", terminal.stdout)
                self.assertEqual(content, path.read_text())

    def test_keys_must_be_unique(self) -> None:
        with self.assertRaisesRegex(ValueError, "form keys must be unique: port"):
            tui.ask_form([tui.Field("port", "Port"), tui.Field("port", "Other port")])


class MenuTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []

    def action(self, name: str):
        async def act() -> None:
            await asyncio.sleep(0)
            self.calls.append(name)

        return act

    def menu(self) -> tui.Menu:
        async def failing() -> None:
            raise RuntimeError("nginx -t failed")

        async def cancelled() -> None:
            tui.ask("Domain")

        async def load_security() -> tui.Menu:
            self.calls.append("loaded")
            return tui.Menu("Security", [tui.Item("Audit SSH", action=self.action("audit"))])

        async def broken_loader() -> tui.Menu:
            raise ImportError("no module named security")

        nginx = tui.Menu(
            "Nginx",
            [tui.Item("Reload", action=self.action("reload")), tui.Item("Test config", action=failing)],
        )
        return tui.Menu(
            "Maintenance",
            [
                tui.Item("Status", action=self.action("status")),
                tui.Item("Nginx", submenu=nginx),
                tui.Item("Security", load=load_security),
                tui.Item("Broken", load=broken_loader),
                tui.Item("Add site", action=cancelled),
            ],
        )

    def test_actions_run_and_the_menu_comes_back_until_quit(self) -> None:
        with tui.simulate_input(["1", "status", "0"]) as terminal:
            run(tui.run_menu(self.menu()))
        self.assertEqual(["status", "status"], self.calls)
        self.assertEqual(3, terminal.stdout.count(" Maintenance "))
        self.assertIn(" 1. Status\n 2. Nginx\n 3. Security\n 4. Broken\n 5. Add site\n 0. Quit\n", terminal.stdout)

    def test_an_entry_whose_label_is_a_number_is_chosen_by_that_label(self) -> None:
        menu = tui.Menu("Ports", [tui.Item("2", action=self.action("two")), tui.Item("1", action=self.action("one"))])
        with tui.simulate_input(["1", "2", "0"]):
            run(tui.run_menu(menu))
        self.assertEqual(["one", "two"], self.calls)

    def test_submenus_go_back_and_loaded_ones_are_built_when_chosen(self) -> None:
        with tui.simulate_input(["2", "1", "0", "3", "1", "0", "0"]) as terminal:
            run(tui.run_menu(self.menu()))
        self.assertEqual(["reload", "loaded", "audit"], self.calls)
        self.assertIn(" 0. Back\n", terminal.stdout)

    def test_failures_are_shown_and_the_menu_stays(self) -> None:
        with tui.simulate_input(["2", "2", "0", "4", "5", KeyboardInterrupt, "9", "0"]) as terminal:
            run(tui.run_menu(self.menu()))
        self.assertIn("✗ nginx -t failed", terminal.stderr)
        self.assertIn("✗ no module named security", terminal.stderr)
        self.assertIn("⚠ Enter a number from 0 to 5.", terminal.stdout)
        self.assertEqual([], self.calls)

    def test_cancelling_inside_a_load_just_returns_to_the_menu(self) -> None:
        async def ask_first() -> tui.Menu:
            tui.ask("Which server")
            raise AssertionError("not reached")

        menu = tui.Menu("Tools", [tui.Item("Servers", load=ask_first), tui.Item("Status", action=self.action("status"))])
        with tui.simulate_input(["1", KeyboardInterrupt, "2", "0"]) as terminal:
            run(tui.run_menu(menu))
        self.assertEqual(["status"], self.calls)
        self.assertNotIn("✗", terminal.stderr)

    def test_the_traceback_of_a_failure_is_logged_at_debug(self) -> None:
        # The screen keeps one line; debug mode, which logs DEBUG, gets the traceback.
        with self.assertLogs("oldman.cli.tui.menus", level="DEBUG") as logs, tui.simulate_input(["2", "2", "0", "4", "0"]):
            run(tui.run_menu(self.menu()))
        self.assertEqual([logging.DEBUG, logging.DEBUG], [record.levelno for record in logs.records])
        self.assertEqual(
            ["Menu item Test config failed", "Menu item Broken failed"],
            [record.getMessage() for record in logs.records],
        )
        self.assertEqual(
            ["RuntimeError('nginx -t failed')", "ImportError('no module named security')"],
            [repr(record.exc_info[1]) for record in logs.records if record.exc_info],
        )

    def test_after_action_exit_leaves_every_level(self) -> None:
        with tui.simulate_input(["2", "1"]) as terminal:
            run(tui.run_menu(self.menu(), after_action="exit"))
        self.assertEqual(["reload"], self.calls)
        self.assertEqual([], terminal.remaining)

    def test_ctrl_c_or_end_of_input_leaves_a_level(self) -> None:
        with tui.simulate_input(["2", EOFError, KeyboardInterrupt]) as terminal:
            run(tui.run_menu(self.menu(), quit_label="Exit", back_label="Up"))
        self.assertIn(" 0. Exit\n", terminal.stdout)
        self.assertIn(" 0. Up\n", terminal.stdout)
        self.assertEqual(2, terminal.stdout.count(" Maintenance "))

    def test_items_and_menus_are_checked_when_built(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one of action, submenu or load; got none"):
            tui.Item("Empty")
        with self.assertRaisesRegex(ValueError, "got \\['action', 'submenu'\\]"):
            tui.Item("Both", action=self.action("x"), submenu=tui.Menu("Sub", [tui.Item("A", action=self.action("a"))]))
        with self.assertRaisesRegex(ValueError, "has no items"):
            tui.Menu("Nothing", [])

    def test_a_menu_needs_a_terminal(self) -> None:
        saved = sys.stdin
        sys.stdin = io.StringIO()
        try:
            with self.assertRaisesRegex(tui.NotInteractive, "Maintenance needs an answer"):
                run(tui.run_menu(self.menu()))
        finally:
            sys.stdin = saved


if __name__ == "__main__":
    unittest.main()
