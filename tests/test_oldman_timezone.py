"""Timezone helpers must bind the settings object published by bootstrap."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_fresh_python(source: str) -> subprocess.CompletedProcess[str]:
    """Run one isolated timezone settings lifecycle."""
    return subprocess.run(
        (sys.executable, "-c", textwrap.dedent(source)),
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


class TimezoneSettingsTest(unittest.TestCase):
    """Protect late bootstrap for a manager imported before configuration."""

    def test_manager_reads_the_current_default_timezone_after_bootstrap(self) -> None:
        """A pre-created manager must use the configured typed settings object."""
        completed = run_fresh_python(
            """
            from datetime import UTC, datetime

            import oldman.conf as conf
            from oldman.conf.schemas import DefaultSettings
            from oldman.utils.timezone import TimezoneManager

            manager = TimezoneManager()

            configured = DefaultSettings.model_validate(
                {"core": {"time_zone": "America/Los_Angeles"}}
            )
            conf._publish_settings(configured)

            assert manager.get_timezone(None).key == "America/Los_Angeles"
            converted = manager.convert_to_local(
                datetime(2026, 7, 12, 20, 0, tzinfo=UTC),
                "",
            )
            assert converted.tzinfo.key == "America/Los_Angeles"
            """
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
