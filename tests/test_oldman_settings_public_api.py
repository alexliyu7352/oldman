"""Process-wide Settings publication contracts."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class OldmanSettingsPublicApiTest(unittest.TestCase):
    """Verify bootstrap owns one process-wide published settings object."""

    def test_bootstrap_publication_has_no_legacy_setup_proxies(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import oldman.conf as conf
                    from oldman.conf.schemas import DefaultSettings

                    class ProjectSettings(DefaultSettings):
                        public_value: str = "default"

                    try:
                        conf.settings
                    except RuntimeError as exc:
                        assert "not configured" in str(exc)
                    else:
                        raise AssertionError("settings existed before bootstrap")

                    configured = ProjectSettings.model_validate(
                        {"public_value": "configured"}
                    )
                    conf._publish_settings(configured)

                    assert configured is conf.settings
                    assert configured.public_value == "configured"
                    assert "setup" not in conf.__all__
                    assert not hasattr(conf, "setup")
                    assert "settings_class" not in conf.__all__
                    assert "settings_manager" not in conf.__all__
                    assert not hasattr(conf, "get_typed_settings")

                    try:
                        conf._publish_settings(ProjectSettings())
                    except RuntimeError as exc:
                        assert "already configured" in str(exc)
                    else:
                        raise AssertionError("second bootstrap replaced process settings")
                    """
                ),
            ],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
