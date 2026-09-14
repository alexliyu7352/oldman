"""CLI localization, lazy-import, and command-lifecycle contracts."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from babel.messages.pofile import read_po

from oldman.cli import main as oldman_main
from oldman.cli.localization import resolve_cli_language
from oldman.i18n import gettext

ROOT = Path(__file__).resolve().parents[1]


def cli_environment(
    config_home: Path,
    *,
    language: str | None = "en",
) -> dict[str, str]:
    """Return a deterministic subprocess environment for CLI tests."""
    environment = os.environ.copy()
    python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(ROOT) if not python_path else f"{ROOT}{os.pathsep}{python_path}"
    environment["XDG_CONFIG_HOME"] = str(config_home)
    environment["LANG"] = "C"
    environment.pop("LANGUAGE", None)
    environment.pop("LC_ALL", None)
    environment.pop("LC_MESSAGES", None)
    if language is None:
        environment.pop("OLDMAN_CLI_LANGUAGE", None)
    else:
        environment["OLDMAN_CLI_LANGUAGE"] = language
    return environment


def run_cli(
    cwd: Path,
    config_home: Path,
    *args: str,
    language: str | None = "en",
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the public module entry point in an isolated subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "oldman.cli", *args],
        cwd=cwd,
        env=cli_environment(config_home, language=language),
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
    )


class OldmanCliLocalizationTest(unittest.TestCase):
    """Verify CLI language state remains independent from project i18n."""

    def test_public_package_import_is_cold(self) -> None:
        """Importing oldman.cli must not import Typer, Sanic, or Web."""
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, oldman.cli; "
                "assert 'typer' not in sys.modules; "
                "assert 'sanic' not in sys.modules; "
                "assert 'oldman.web' not in sys.modules",
            ],
            cwd=ROOT,
            env=cli_environment(Path("/tmp/oldman-cli-cold-import")),
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_alias_is_saved_canonically_and_help_uses_shared_catalog(self) -> None:
        """CLI accepts registered aliases but persists the canonical code."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_home = Path(temporary_directory)
            changed = run_cli(
                Path(temporary_directory),
                config_home,
                "language",
                "set",
                "zh-CN",
            )
            config = json.loads((config_home / "oldman" / "cli.json").read_text(encoding="utf-8"))
            help_result = run_cli(
                Path(temporary_directory),
                config_home,
                "--help",
                language=None,
            )

        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertIn("CLI 语言已设置为 zh-Hans", changed.stdout)
        self.assertEqual(config, {"language": "zh-Hans"})
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("用法:", help_result.stdout)
        self.assertIn("选项:", help_result.stdout)
        self.assertIn("框架命令:", help_result.stdout)

    def test_root_help_separates_framework_commands_and_services(self) -> None:
        """Root help groups cold-discovered services without changing command paths."""
        expected = {
            "en": ("Framework commands:", "Services:", "Web service web."),
            "zh-Hans": ("框架命令:", "服务:", "Web 服务 web。"),
            "zh-Hant": ("框架命令:", "服務:", "Web 服務 web。"),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            (project / "pyproject.toml").write_text(
                '[project]\nname = "cli-help-probe"\nversion = "0"\n',
                encoding="utf-8",
            )
            services = project / "services"
            services.mkdir()
            (services / "web.py").write_text(
                "class Web(WebApplication):\n    pass\n",
                encoding="utf-8",
            )

            for language, markers in expected.items():
                with self.subTest(language=language):
                    completed = run_cli(
                        project,
                        project / ".config" / language,
                        "--help",
                        language=language,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    for marker in markers:
                        self.assertIn(marker, completed.stdout)

    def test_each_builtin_language_localizes_help_and_usage_errors(self) -> None:
        """All built-in catalogs cover structural help and common parser errors."""
        expected = {
            "en": ("Usage:", "No such option", "Aborted."),
            "zh-Hans": ("用法:", "没有此选项", "已中止。"),
            "zh-Hant": ("用法:", "沒有此選項", "已中止。"),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for language, markers in expected.items():
                with self.subTest(language=language):
                    help_result = run_cli(
                        root,
                        root / language,
                        "--help",
                        language=language,
                    )
                    bad_option = run_cli(
                        root,
                        root / language,
                        "--bad",
                        language=language,
                    )
                    bad_choice = run_cli(
                        root,
                        root / language,
                        "startproject",
                        "probe",
                        language=language,
                        input_text="invalid\n",
                    )

                    self.assertEqual(help_result.returncode, 0, help_result.stderr)
                    self.assertEqual(bad_option.returncode, 2, bad_option.stderr)
                    self.assertEqual(bad_choice.returncode, 1, bad_choice.stderr)
                    self.assertIn(markers[0], help_result.stdout)
                    self.assertIn(markers[1], bad_option.stderr)
                    self.assertIn(markers[2], bad_choice.stderr)

    def test_environment_override_does_not_replace_saved_language(self) -> None:
        """One-process environment selection stays separate from persistence."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_home = Path(temporary_directory)
            saved = run_cli(
                Path(temporary_directory),
                config_home,
                "language",
                "set",
                "zh-Hans",
            )
            shown = run_cli(
                Path(temporary_directory),
                config_home,
                "language",
                "show",
                language="zh-Hant",
            )

        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("目前語言：zh-Hant", shown.stdout)
        self.assertIn("已儲存語言：zh-Hans", shown.stdout)
        self.assertIn("OLDMAN_CLI_LANGUAGE=zh-Hant", shown.stdout)

    def test_non_interactive_help_does_not_write_first_run_config(self) -> None:
        """Captured help uses the system fallback without prompting or writing."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_home = Path(temporary_directory)
            completed = run_cli(
                Path(temporary_directory),
                config_home,
                "--help",
                language=None,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Usage:", completed.stdout)
            self.assertFalse((config_home / "oldman" / "cli.json").exists())

    def test_interactive_first_choice_is_persisted(self) -> None:
        """The dependency-free first-run prompt writes its selected canonical code."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_home = Path(temporary_directory)
            with (
                patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(config_home),
                        "LANG": "C",
                    },
                    clear=False,
                ),
                patch(
                    "oldman.cli.localization._should_prompt",
                    return_value=True,
                ),
                patch("builtins.input", return_value="2"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                state = resolve_cli_language(["--help"])

            config = json.loads((config_home / "oldman" / "cli.json").read_text(encoding="utf-8"))

        self.assertEqual(state.effective, "zh-Hans")
        self.assertEqual(state.source, "prompt")
        self.assertEqual(config, {"language": "zh-Hans"})

    def test_cold_help_does_not_import_broken_project_runtime(self) -> None:
        """Root help never imports config.settings and removed root groups stay absent."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            config = project / "config"
            config.mkdir()
            (config / "__init__.py").write_text("", encoding="utf-8")
            (config / "settings.py").write_text(
                "raise RuntimeError('runtime settings imported')\n",
                encoding="utf-8",
            )
            config_home = project / ".config"

            for command in ("db", "i18n", "language"):
                with self.subTest(command=command):
                    completed = run_cli(
                        project,
                        config_home,
                        command,
                        "--help",
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        completed.stderr + completed.stdout,
                    )

            root_help = run_cli(project, config_home, "--help")
            self.assertEqual(
                0,
                root_help.returncode,
                root_help.stderr + root_help.stdout,
            )
            self.assertNotIn("runtime settings imported", root_help.stderr)
            for removed in ("config", "list", "settings", "static"):
                unavailable = run_cli(
                    project,
                    config_home,
                    removed,
                    "--help",
                )
                self.assertEqual(2, unavailable.returncode)
                self.assertIn("No such command", unavailable.stderr)

    def test_i18n_commands_delegate_and_reset_translation_context(self) -> None:
        """Catalog commands stay thin and one in-process invocation never leaks."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": temporary_directory,
                    "OLDMAN_CLI_LANGUAGE": "zh-Hans",
                },
                clear=False,
            ):
                output = io.StringIO()
                with (
                    patch("oldman.i18n.commands.extract") as extract,
                    contextlib.redirect_stdout(output),
                ):
                    extract_code = oldman_main(["i18n", "extract"])
                with (
                    patch("oldman.i18n.commands.init") as initialize,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    init_code = oldman_main(["i18n", "init", "de-DE"])

        self.assertEqual(extract_code, 0)
        self.assertEqual(init_code, 0)
        extract.assert_called_once_with()
        initialize.assert_called_once_with("de_DE")
        self.assertIn("正在提取翻译消息", output.getvalue())
        self.assertEqual(gettext("Usage"), "Usage")
        import oldman.cli as cli_package

        self.assertTrue(callable(cli_package.main))

    def test_command_failure_keeps_the_original_exception(self) -> None:
        """The abort handler must not mask an unrelated command failure."""
        failure = RuntimeError("Catalog extraction failed")
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(os.environ, cli_environment(Path(temporary_directory))),
            patch("oldman.i18n.commands.extract", side_effect=failure),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(RuntimeError) as caught,
        ):
            oldman_main(["i18n", "extract"])
        self.assertIs(caught.exception, failure)

    def test_invalid_language_is_a_usage_error(self) -> None:
        """Unsupported CLI language input exits 2 and lists canonical choices."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            completed = run_cli(
                Path(temporary_directory),
                Path(temporary_directory) / ".config",
                "language",
                "set",
                "de",
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("en, zh-Hans, zh-Hant", completed.stderr)

    def test_builtin_cli_catalogs_have_no_untranslated_or_fuzzy_messages(self) -> None:
        """Published Simplified and Traditional catalogs cover every active key."""
        locales = ROOT / "oldman" / "cli" / "locales"
        for locale_name in ("zh_Hans", "zh_Hant"):
            with self.subTest(locale=locale_name):
                catalog_path = locales / locale_name / "LC_MESSAGES" / "messages.po"
                with catalog_path.open("rb") as catalog_file:
                    catalog = read_po(catalog_file, locale=locale_name)
                incomplete = [message.id for message in catalog if message.id and (not message.string or "fuzzy" in message.flags)]
                self.assertEqual([], incomplete)

    def test_release_artifacts_include_cli_catalogs(self) -> None:
        """Wheel and sdist both publish the runtime and source catalog assets."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            completed = subprocess.run(
                ["uv", "build", "--out-dir", str(output), "--no-sources"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            wheel = next(output.glob("*.whl"))
            sdist = next(output.glob("*.tar.gz"))
            with zipfile.ZipFile(wheel) as archive:
                wheel_members = set(archive.namelist())
            with tarfile.open(sdist, "r:gz") as archive:
                sdist_members = {
                    Path(member.name).relative_to(Path(member.name).parts[0]).as_posix()
                    for member in archive.getmembers()
                    if len(Path(member.name).parts) > 1
                }
        for locale_name in ("zh_Hans", "zh_Hant"):
            runtime_catalog = f"oldman/cli/locales/{locale_name}/LC_MESSAGES/messages.mo"
            source_catalog = f"oldman/cli/locales/{locale_name}/LC_MESSAGES/messages.po"
            self.assertIn(runtime_catalog, wheel_members)
            self.assertIn(source_catalog, sdist_members)
        self.assertIn("oldman/cli/locales/messages.pot", sdist_members)
        self.assertIn("oldman/cli/babel.cfg", sdist_members)
        self.assertIn("oldman/cli/locales/README.md", sdist_members)


if __name__ == "__main__":
    unittest.main()
