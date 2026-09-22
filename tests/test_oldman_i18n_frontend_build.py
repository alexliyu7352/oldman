"""The framework builds the browser catalogs and the frontend language manifest."""

from __future__ import annotations

import inspect
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from oldman.cli import i18n_commands
from oldman.web.i18n import frontend_build

ROOT = Path(__file__).resolve().parents[1]
I18N_CLI = ROOT / "frontend" / "packages" / "oldman-web" / "bin" / "oldman-web-i18n.mjs"
COMPILER = ("node", str(I18N_CLI))


def write_settings(path: Path) -> None:
    """Write one compact standard-language test configuration."""
    path.write_text(
        textwrap.dedent(
            """
            i18n:
              default_language: zh-Hans
              languages:
                en: {}
                zh-Hans:
                  flag: cn
            """
        ).strip(),
        encoding="utf-8",
    )


class FrontendI18nBuildTest(unittest.TestCase):
    """Catalog set, manifest and atomic publication behaviour."""

    def test_language_manifest_uses_profiles_and_standard_codes(self) -> None:
        """Compact settings inherit metadata without exposing Babel IDs."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "settings.yaml"
            output_file = root / "languages.ts"
            write_settings(settings_file)

            frontend_build.write_language_manifest(
                output_file,
                settings_file,
            )
            output = output_file.read_text(encoding="utf-8")

        self.assertIn('export const defaultLanguage = "zh-Hans";', output)
        self.assertIn('code: "zh-Hans"', output)
        self.assertIn('locale: "zh-Hans"', output)
        self.assertIn('aliases: ["zh-CN", "zh-SG"]', output)
        self.assertIn('flagUrl: "/static/oldman/images/flags/cn.svg"', output)
        self.assertIn('catalogPath: "i18n/zh-hans.json"', output)
        self.assertNotIn("zh_Hans", output)

    def test_user_language_metadata_overrides_profiles(self) -> None:
        """Explicit aliases, names, and flags remain project-owned."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "settings.yaml"
            output_file = root / "languages.ts"
            settings_file.write_text(
                textwrap.dedent(
                    """
                    i18n:
                      default_language: fr
                      languages:
                        fr:
                          aliases: [fr-FR]
                          name: Français
                          flag: images/fr.svg
                    """
                ).strip(),
                encoding="utf-8",
            )

            frontend_build.write_language_manifest(
                output_file,
                settings_file,
            )
            output = output_file.read_text(encoding="utf-8")

        self.assertIn('aliases: ["fr-FR"]', output)
        self.assertIn('name: "Français"', output)
        self.assertIn('flagUrl: "/static/images/fr.svg"', output)

    def test_unknown_default_language_is_rejected(self) -> None:
        """The language manifest must not silently choose another default."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "settings.yaml"
            settings_file.write_text(
                "i18n:\n"
                "  default_language: fr\n"
                "  languages:\n"
                "    en: {}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "default_language"):
                frontend_build.read_i18n_languages(settings_file)

    def test_language_catalogs_use_unified_po_and_filter_backend_ids(self) -> None:
        """The adapter reads messages.po and publishes only AST frontend IDs."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "settings.yaml"
            locales_dir = root / "locales"
            output_dir = root / "public" / "i18n"
            write_settings(settings_file)
            _, configured = frontend_build.read_i18n_languages(
                settings_file
            )
            po_directory = locales_dir / "zh_Hans" / "LC_MESSAGES"
            po_directory.mkdir(parents=True)
            (po_directory / "messages.po").write_text(
                'msgid "Request failed"\n'
                'msgstr "请求失败"\n\n'
                'msgid "Backend only"\n'
                'msgstr "后端专用"\n',
                encoding="utf-8",
            )

            frontend_build.write_language_catalogs(
                output_dir,
                locales_dir,
                configured,
                compiler_command=COMPILER,
                project_root=ROOT,
            )
            english = json.loads(
                (output_dir / "en.json").read_text(encoding="utf-8")
            )
            chinese = json.loads(
                (output_dir / "zh-hans.json").read_text(encoding="utf-8")
            )

        self.assertEqual(english, {"locale": "en", "messages": {}})
        self.assertEqual(chinese["messages"]["Request failed"], "请求失败")
        self.assertNotIn("Backend only", chinese["messages"])

    def test_complete_publish_removes_stale_catalogs(self) -> None:
        """Every run publishes all configured languages and removes old JSON."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "settings.yaml"
            locales_dir = root / "locales"
            output_dir = root / "public" / "i18n"
            manifest = root / "src" / "i18n" / "generated.ts"
            write_settings(settings_file)
            output_dir.mkdir(parents=True)
            (output_dir / "fr.json").write_text(
                '{"locale":"fr","messages":{}}\n',
                encoding="utf-8",
            )
            manifest.parent.mkdir(parents=True)
            manifest.write_text("old manifest\n", encoding="utf-8")

            frontend_build.build_frontend_i18n(
                output_dir,
                locales_dir,
                settings_file,
                manifest,
                compiler_command=COMPILER,
                project_root=ROOT,
            )

            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                {"en.json", "zh-hans.json"},
            )
            self.assertIn(
                'export const defaultLanguage = "zh-Hans";',
                manifest.read_text(encoding="utf-8"),
            )

    def test_compile_failure_preserves_previous_publication(self) -> None:
        """A failed staged compile cannot replace catalogs or their manifest."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "settings.yaml"
            locales_dir = root / "locales"
            output_dir = root / "public" / "i18n"
            manifest = root / "src" / "i18n" / "generated.ts"
            write_settings(settings_file)
            po_directory = locales_dir / "zh_Hans" / "LC_MESSAGES"
            po_directory.mkdir(parents=True)
            (po_directory / "messages.po").write_text(
                'msgid "Request failed"\nmsgstr "请求失败"\n',
                encoding="utf-8",
            )
            output_dir.mkdir(parents=True)
            previous_catalog = '{"locale":"previous","messages":{}}\n'
            (output_dir / "previous.json").write_text(
                previous_catalog,
                encoding="utf-8",
            )
            manifest.parent.mkdir(parents=True)
            manifest.write_text("previous manifest\n", encoding="utf-8")

            with (
                mock.patch.object(
                    frontend_build,
                    "compile_project_frontend_catalog",
                    side_effect=RuntimeError("compile failed"),
                ),
                self.assertRaisesRegex(RuntimeError, "compile failed"),
            ):
                frontend_build.build_frontend_i18n(
                    output_dir,
                    locales_dir,
                    settings_file,
                    manifest,
                    compiler_command=COMPILER,
                    project_root=ROOT,
                )

            self.assertEqual(
                (output_dir / "previous.json").read_text(encoding="utf-8"),
                previous_catalog,
            )
            self.assertEqual(
                manifest.read_text(encoding="utf-8"),
                "previous manifest\n",
            )

    def test_a_manifest_inside_the_catalog_directory_is_refused(self) -> None:
        """发布目录的那一步会整体替换它，所以这种接线必须当场报错，而不是构建完才发现清单没了。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "web_settings.yaml"
            write_settings(settings_file)
            output_dir = root / "frontend" / "public" / "i18n"

            with self.assertRaisesRegex(ValueError, "catalog"):
                frontend_build.build_frontend_i18n(
                    output_dir,
                    root / "locales",
                    settings_file,
                    output_dir / "languages.json",
                    compiler_command=COMPILER,
                    project_root=root,
                )

    def test_the_cli_names_the_missing_settings_file(self) -> None:
        """语言集合来自服务配置，配置文件不存在时要给一句话，而不是 YAML 读取的堆栈。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            with self.assertRaisesRegex(ValueError, "web_settings.yaml"):
                i18n_commands.build_frontend_catalogs(project_root=root, service="web")

    def test_the_cli_publishes_every_configured_language(self) -> None:
        """没有"只发布部分语言"的开关：缺目录的语言会让前端退回 msgid，必须整套一起发。"""
        parameters = {
            parameter.name
            for parameter in inspect.signature(i18n_commands.build_frontend_catalogs).parameters.values()
        }

        self.assertNotIn("languages", parameters)

    def test_manifest_publish_failure_restores_previous_catalogs(self) -> None:
        """The old catalog directory must match an unchanged old manifest."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staged_catalogs = root / "staging" / "catalogs"
            staged_catalogs.mkdir(parents=True)
            (staged_catalogs / "en.json").write_text(
                '{"locale":"en","messages":{}}\n',
                encoding="utf-8",
            )
            output_dir = root / "public" / "i18n"
            output_dir.mkdir(parents=True)
            (output_dir / "previous.json").write_text(
                '{"locale":"previous","messages":{}}\n',
                encoding="utf-8",
            )
            staged_manifest = root / "staged-generated.ts"
            staged_manifest.write_text("new manifest\n", encoding="utf-8")
            manifest = root / "src" / "i18n" / "generated.ts"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("previous manifest\n", encoding="utf-8")
            original_replace = Path.replace

            def fail_manifest_replace(source: Path, target: Path) -> Path:
                """Simulate only the final manifest replacement failing."""
                if source == staged_manifest:
                    raise OSError("manifest publish failed")
                return original_replace(source, target)

            with (
                mock.patch.object(Path, "replace", new=fail_manifest_replace),
                self.assertRaisesRegex(OSError, "manifest publish failed"),
            ):
                frontend_build.publish_staged_i18n(
                    staged_catalogs,
                    output_dir,
                    staged_manifest,
                    manifest,
                )

            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                {"previous.json"},
            )
            self.assertEqual(
                manifest.read_text(encoding="utf-8"),
                "previous manifest\n",
            )


if __name__ == "__main__":
    unittest.main()
