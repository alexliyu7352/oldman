"""oldman.ops: configuration file edits, os-release, and systemd through a stand-in systemctl."""

from __future__ import annotations

import asyncio
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from oldman import ops
from oldman.ops import files as ops_files
from oldman.ops import systemd


class EditMarkedBlockTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_created_appended_replaced_and_left_alone(self) -> None:
        limits = self.root / "limits.conf"
        self.assertTrue(ops.edit_marked_block(limits, "LIMITS", "* soft nofile 65535\n", follow_symlinks=False))
        self.assertEqual("# >>> LIMITS\n* soft nofile 65535\n# <<< LIMITS\n", limits.read_text())

        limits.write_text("root hard core 0")  # no newline at the end
        ops.edit_marked_block(limits, "LIMITS", "* soft nofile 65535", follow_symlinks=False)
        ops.edit_marked_block(limits, "SYSCTL", "vm.swappiness = 10", follow_symlinks=False)
        self.assertTrue(ops.edit_marked_block(limits, "LIMITS", "* soft nofile 1048576", follow_symlinks=False))
        self.assertEqual(
            "root hard core 0\n# >>> LIMITS\n* soft nofile 1048576\n# <<< LIMITS\n# >>> SYSCTL\nvm.swappiness = 10\n# <<< SYSCTL\n",
            limits.read_text(),
        )

        written = limits.stat().st_mtime_ns
        self.assertFalse(ops.edit_marked_block(limits, "LIMITS", "* soft nofile 1048576\n\n", follow_symlinks=False))
        self.assertEqual(written, limits.stat().st_mtime_ns)

    def test_another_comment_mark_and_a_marker_that_is_only_a_prefix(self) -> None:
        ini = self.root / "php.ini"
        ini.write_text("; >>> OPCACHE_EXTRA\nkeep\n; <<< OPCACHE_EXTRA\n")
        ops.edit_marked_block(ini, "OPCACHE", "opcache.enable=1", follow_symlinks=False, comment=";")
        self.assertEqual(
            "; >>> OPCACHE_EXTRA\nkeep\n; <<< OPCACHE_EXTRA\n; >>> OPCACHE\nopcache.enable=1\n; <<< OPCACHE\n",
            ini.read_text(),
        )

    def test_follow_symlinks_is_the_callers_choice(self) -> None:
        target = self.root / "real.conf"
        target.write_text("")
        link = self.root / "link.conf"
        link.symlink_to(target)
        ops.edit_marked_block(link, "A", "a", follow_symlinks=True)
        self.assertTrue(link.is_symlink())
        self.assertIn("a", target.read_text())
        ops.edit_marked_block(link, "B", "b", follow_symlinks=False)
        self.assertFalse(link.is_symlink())
        self.assertNotIn("b", target.read_text())


class DirectiveTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.sshd = Path(directory.name) / "sshd_config"
        self.sshd.write_text(
            textwrap.dedent(
                """\
                # Port numbers below 1024 need root.
                #Port 22
                PortForwarding yes
                #PermitRootLogin prohibit-password
                port 2200
                """
            )
        )

    def test_every_line_for_the_key_takes_the_value_and_prose_stays(self) -> None:
        self.assertTrue(ops.set_directive(self.sshd, "Port", "43589", follow_symlinks=False))
        self.assertEqual(
            "# Port numbers below 1024 need root.\nPort 43589\nPortForwarding yes\n#PermitRootLogin prohibit-password\nPort 43589\n",
            self.sshd.read_text(),
        )
        self.assertFalse(ops.set_directive(self.sshd, "Port", "43589", follow_symlinks=False))

    def test_a_missing_key_is_appended(self) -> None:
        self.sshd.write_text("PasswordAuthentication yes")
        ops.set_directive(self.sshd, "PermitRootLogin", "no", follow_symlinks=False)
        self.assertEqual("PasswordAuthentication yes\nPermitRootLogin no\n", self.sshd.read_text())
        created = self.sshd.with_name("new_config")
        ops.set_directive(created, "Port", "22", follow_symlinks=False)
        self.assertEqual("Port 22\n", created.read_text())

    def test_reading_takes_the_first_setting_that_is_not_commented_out(self) -> None:
        self.assertEqual("2200", ops.read_directive(self.sshd, "PORT"))
        self.assertIsNone(ops.read_directive(self.sshd, "PermitRootLogin"))
        self.assertEqual("22", ops.read_directive(self.sshd, "ListenAddress", "22"))
        self.assertEqual("x", ops.read_directive(self.sshd.with_name("missing"), "Port", "x"))

    def test_an_equals_separator(self) -> None:
        sysctl = self.sshd.with_name("sysctl.conf")
        sysctl.write_text("#net.ipv4.ip_forward=1\nnet.core.somaxconn = 128\n")
        ops.set_directive(sysctl, "net.ipv4.ip_forward", "1", follow_symlinks=False, separator=" = ")
        ops.set_directive(sysctl, "net.core.somaxconn", "4096", follow_symlinks=False, separator=" = ")
        self.assertEqual("net.ipv4.ip_forward = 1\nnet.core.somaxconn = 4096\n", sysctl.read_text())
        self.assertEqual("4096", ops.read_directive(sysctl, "net.core.somaxconn", separator="="))


class OsReleaseTest(unittest.TestCase):
    def test_values_are_unquoted_and_other_lines_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "os-release"
            release.write_text(
                '# comment\nNAME="Ubuntu"\nVERSION_ID="22.04"\nID=ubuntu\n\nPRETTY_NAME="Ubuntu \\"Jammy\\""\nVARIANT=\'Server Edition\'\n'
            )
            self.assertEqual(
                {"NAME": "Ubuntu", "VERSION_ID": "22.04", "ID": "ubuntu", "PRETTY_NAME": 'Ubuntu "Jammy"', "VARIANT": "Server Edition"},
                ops.os_release(release),
            )
            self.assertEqual({}, ops.os_release(Path(directory) / "missing"))

    def test_without_a_path_it_falls_back_to_usr_lib(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fallback = Path(directory) / "usr-lib-os-release"
            fallback.write_text("ID=debian\n")
            with patch.object(ops_files, "_OS_RELEASE_PATHS", (Path(directory) / "etc-os-release", fallback)):
                self.assertEqual({"ID": "debian"}, ops.os_release())


FAKE_SYSTEMCTL = """#!/bin/sh
echo "$*" >> "$FAKE_SYSTEMCTL_LOG"
case "$1" in
  is-active) grep -qx "$3" "$FAKE_SYSTEMCTL_ACTIVE" ;;
  reload|restart) [ "$2" != "broken" ] || { echo "Job for broken.service failed." >&2; exit 1; } ;;
esac
"""


class SystemdTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.systemctl = root / "systemctl"
        self.systemctl.write_text(FAKE_SYSTEMCTL)
        self.systemctl.chmod(self.systemctl.stat().st_mode | stat.S_IXUSR)
        self.log = root / "calls.log"
        active = root / "active"
        active.write_text("sshd\nnginx\nbroken\n")
        environment = patch.dict(os.environ, {"FAKE_SYSTEMCTL_LOG": str(self.log), "FAKE_SYSTEMCTL_ACTIVE": str(active)})
        environment.start()
        self.addCleanup(environment.stop)
        self.command = (str(self.systemctl),)

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_is_active(self) -> None:
        self.assertTrue(asyncio.run(systemd.is_active("nginx", command=self.command)))
        self.assertFalse(asyncio.run(systemd.is_active("apache2", command=self.command)))
        self.assertEqual(["is-active --quiet nginx", "is-active --quiet apache2"], self.calls())

    def test_restart_takes_the_first_candidate_that_runs(self) -> None:
        self.assertEqual("sshd", asyncio.run(systemd.restart("ssh", "sshd", command=self.command)))
        self.assertEqual(["is-active --quiet ssh", "is-active --quiet sshd", "restart sshd"], self.calls())
        self.assertIsNone(asyncio.run(systemd.restart("apache2", command=self.command)))
        self.assertNotIn("restart apache2", self.calls())

    def test_reload_daemon_reload_and_failures(self) -> None:
        asyncio.run(systemd.reload("nginx", command=self.command))
        asyncio.run(systemd.daemon_reload(command=self.command))
        self.assertEqual(["reload nginx", "daemon-reload"], self.calls())
        with self.assertRaises(subprocess.CalledProcessError) as failed:
            asyncio.run(systemd.reload("broken", command=self.command))
        self.assertIn("Job for broken.service failed.", failed.exception.stderr)
        with self.assertRaises(subprocess.CalledProcessError):
            asyncio.run(systemd.restart("broken", command=self.command))

    def test_systemctl_stays_on_the_tools_terminal(self) -> None:
        # A child in a session of its own has no terminal, where sudo could not ask for a password.
        session = self.systemctl.with_name("session")
        probe = self.systemctl.with_name("session-systemctl")
        probe.write_text(f"#!{sys.executable}\nimport os\nopen({str(session)!r}, 'w').write(str(os.getsid(0)))\n")
        probe.chmod(probe.stat().st_mode | stat.S_IXUSR)
        asyncio.run(systemd.daemon_reload(command=(str(probe),)))
        self.assertEqual(os.getsid(0), int(session.read_text()))

    def test_without_systemctl_every_function_raises(self) -> None:
        missing = (str(self.systemctl.with_name("missing")),)
        with self.assertRaises(FileNotFoundError):
            asyncio.run(systemd.is_active("nginx", command=missing))
        with self.assertRaises(FileNotFoundError):
            asyncio.run(systemd.restart("ssh", "sshd", command=missing))

    def test_arguments_are_checked(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one unit"):
            asyncio.run(systemd.restart(command=self.command))
        with self.assertRaisesRegex(ValueError, "name the systemctl program"):
            asyncio.run(systemd.is_active("nginx", command=()))


if __name__ == "__main__":
    unittest.main()
