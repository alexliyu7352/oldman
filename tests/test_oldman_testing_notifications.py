"""The shared notification browser gate: host contract, BiDi client and entry point."""

from __future__ import annotations

import json
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from oldman.testing import notifications as gate

ROOT = Path(__file__).resolve().parents[1]


class FirefoxBiDiTest(unittest.TestCase):
    def test_it_connects_to_the_session_endpoint_of_the_given_port(self) -> None:
        with patch.object(gate, "WebSocket") as websocket:
            gate.FirefoxBiDi(47381)

        websocket.assert_called_once_with("ws://127.0.0.1:47381/session")

    def test_it_decodes_standard_remote_values(self) -> None:
        decoded = gate._bidi_value(
            {
                "type": "object",
                "value": [
                    ["path", {"type": "string", "value": "/admin"}],
                    ["topbar", {"type": "boolean", "value": True}],
                    ["count", {"type": "number", "value": 3}],
                ],
            }
        )

        self.assertEqual({"path": "/admin", "topbar": True, "count": 3}, decoded)


class BrowserLanguageTest(unittest.TestCase):
    """门禁断言英文界面文案，所以浏览器语言必须固定，不能跟着开发机的 LANG 走。"""

    def test_chrome_receives_the_gate_language(self) -> None:
        from oldman.testing import browser

        with patch.object(browser.subprocess, "Popen") as popen, patch.object(browser, "find_chrome", return_value="/usr/bin/chrome"):
            browser.launch_chrome(9222, "/tmp/profile", accept_language=gate.GATE_LANGUAGE)

        args = popen.call_args.args[0]
        self.assertIn(f"--lang={gate.GATE_LANGUAGE}", args)
        self.assertIn(f"--accept-lang={gate.GATE_LANGUAGE}", args)
        self.assertEqual("about:blank", args[-1])

    def test_chrome_without_a_language_keeps_the_browser_default(self) -> None:
        from oldman.testing import browser

        with patch.object(browser.subprocess, "Popen") as popen, patch.object(browser, "find_chrome", return_value="/usr/bin/chrome"):
            browser.launch_chrome(9222, "/tmp/profile")

        self.assertEqual([], [argument for argument in popen.call_args.args[0] if "lang" in argument])


class FirefoxConsoleHandoverTest(unittest.TestCase):
    """框架先判完自己的 console 错误再交给宿主，顺序反了宿主的容忍就作废。

    这段逻辑跑在真实 Firefox 里，单测起不了浏览器，所以这里盯的是源码顺序：
    检查、清空、调用 extra_steps 必须按这个次序出现。
    """

    def statement_order(self) -> list[str]:
        """Return the three handover statements in source order."""
        source = (ROOT / "oldman" / "testing" / "notifications.py").read_text(encoding="utf-8")
        body = source[source.index("def _verify_firefox("):]
        marks = {
            "check": body.index("f\"Firefox console errors: {client.console_errors}\""),
            "clear": body.index("client.console_errors.clear()"),
            "extra": body.index("\n            extra_steps(client, context, base_url, evidence)"),
        }
        return sorted(marks, key=lambda name: marks[name])

    def test_the_framework_checks_and_clears_before_the_host_steps(self) -> None:
        self.assertEqual(["check", "clear", "extra"], self.statement_order())


class GateEntryPointTest(unittest.TestCase):
    def test_it_passes_the_host_contract_and_prints_one_machine_readable_record(self) -> None:
        host = gate.HostContract(name="probe", home_path="/", login_path="/login", center_path="/user-notifications")
        captured: dict[str, object] = {}

        def fake_run(**options: object) -> tuple[int, dict[str, object]]:
            captured.update(options)
            return 0, {"ok": True, "browser": "chrome", "host": host.name}

        output = StringIO()
        with patch.object(gate, "run_verification", side_effect=fake_run), patch("sys.stdout", output):
            code = gate.notification_gate_main(
                host=host,
                project_root=ROOT,
                argv=[
                    "--browser",
                    "chrome",
                    "--url",
                    "http://127.0.0.1:8000/",
                    "--config",
                    str(ROOT / "pyproject.toml"),
                    "--username",
                    "gate",
                    "--password",
                    "secret",
                ],
            )

        self.assertEqual(0, code)
        self.assertEqual(host, captured["host"])
        # The trailing slash is dropped so page assertions can join paths directly.
        self.assertEqual("http://127.0.0.1:8000", captured["base_url"])
        self.assertEqual(ROOT, captured["project_root"])
        self.assertIsNone(captured["extra_firefox_steps"])
        self.assertEqual({"ok": True, "browser": "chrome", "host": "probe"}, json.loads(output.getvalue()))

    def test_a_project_can_add_its_own_firefox_steps(self) -> None:
        host = gate.HostContract(name="probe", home_path="/", login_path="/login", center_path="/user-notifications")
        steps = lambda *args: None  # noqa: E731 - a stand-in callable is enough here
        captured: dict[str, object] = {}

        def fake_run(**options: object) -> tuple[int, dict[str, object]]:
            captured.update(options)
            return 1, {"ok": False}

        with patch.object(gate, "run_verification", side_effect=fake_run), patch("sys.stdout", StringIO()):
            code = gate.notification_gate_main(
                host=host,
                project_root=ROOT,
                extra_firefox_steps=steps,
                argv=["--browser", "firefox", "--url", "http://127.0.0.1:8000", "--config", str(ROOT / "pyproject.toml"), "--username", "u", "--password", "p"],
            )

        self.assertEqual(1, code)
        self.assertIs(steps, captured["extra_firefox_steps"])


if __name__ == "__main__":
    unittest.main()
