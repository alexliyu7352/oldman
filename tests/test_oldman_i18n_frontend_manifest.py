"""Contracts for the generated framework frontend translation manifest."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from oldman.i18n.frontend import (
    compile_project_frontend_catalog,
    filter_frontend_catalog_payload,
    frontend_catalog_messages,
    frontend_catalog_payload,
    oldman_web_messages,
)

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = (
    ROOT
    / "frontend"
    / "packages"
    / "oldman-web"
    / "scripts"
    / "generate-i18n-messages.mjs"
)
I18N_CLI = (
    ROOT
    / "frontend"
    / "packages"
    / "oldman-web"
    / "bin"
    / "oldman-web-i18n.mjs"
)


class OldmanFrontendMessageManifestTest(unittest.TestCase):
    """Keep runtime catalogs bound to production TypeScript source."""

    def test_committed_manifest_matches_current_production_sources(self) -> None:
        """A source edit must fail until the generated manifest is refreshed."""
        subprocess.run(
            ("node", str(GENERATOR), "--check"),
            check=True,
            cwd=ROOT,
        )

        messages = oldman_web_messages()

        self.assertTrue(messages)
        self.assertIn("No notifications", {message.id for message in messages})
        self.assertFalse(
            any(
                ".test." in location.path
                or ".spec." in location.path
                or "/fixtures/" in location.path
                for message in messages
                for location in message.locations
            )
        )

    def test_generator_preserves_context_plural_and_parameterized_calls(self) -> None:
        """All four I18nRuntime call shapes retain their gettext identity."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            source_root = repository_root / "frontend" / "src"
            output = repository_root / "messages.json"
            source_root.mkdir(parents=True)
            (source_root / "component.ts").write_text(
                "\n".join(
                    (
                        'this.i18n.t("Save", {name});',
                        'this.i18n.tc("button", "Open");',
                        'this.i18n.tn("{count} file", "{count} files", count);',
                        'this.i18n.tnc("menu", "{count} item", "{count} items", count);',
                    )
                ),
                encoding="utf-8",
            )
            (source_root / "component.test.ts").write_text(
                'this.i18n.t("Test-only message");',
                encoding="utf-8",
            )

            subprocess.run(
                (
                    "node",
                    str(GENERATOR),
                    "--repository-root",
                    str(repository_root),
                    "--source-root",
                    str(source_root),
                    "--output",
                    str(output),
                ),
                check=True,
                cwd=ROOT,
            )
            messages = json.loads(output.read_text(encoding="utf-8"))["messages"]

        identities = {
            (message["context"], message["id"], message["plural"])
            for message in messages
        }
        self.assertEqual(
            identities,
            {
                (None, "Save", None),
                ("button", "Open", None),
                (None, "{count} file", "{count} files"),
                ("menu", "{count} item", "{count} items"),
            },
        )

    def test_generator_rejects_dynamic_message_identity(self) -> None:
        """Dynamic IDs cannot silently disappear from extraction."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            source_root = repository_root / "src"
            source_root.mkdir()
            (source_root / "component.ts").write_text(
                "this.i18n.t(message);",
                encoding="utf-8",
            )

            completed = subprocess.run(
                (
                    "node",
                    str(GENERATOR),
                    "--repository-root",
                    str(repository_root),
                    "--source-root",
                    str(source_root),
                    "--output",
                    str(repository_root / "messages.json"),
                ),
                check=False,
                capture_output=True,
                cwd=ROOT,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must be a static string literal", completed.stderr)

    def test_generator_and_published_cli_share_identical_extraction(
        self,
    ) -> None:
        """The repository generator and public CLI return the same manifest."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            source_root = repository_root / "src"
            output = repository_root / "messages.json"
            source_root.mkdir()
            (source_root / "component.ts").write_text(
                'this.i18n?.tc?.("button", "Open");\n'
                "this.i18n.t(`Save`);\n",
                encoding="utf-8",
            )

            subprocess.run(
                (
                    "node",
                    str(GENERATOR),
                    "--repository-root",
                    str(repository_root),
                    "--source-root",
                    str(source_root),
                    "--output",
                    str(output),
                ),
                check=True,
                cwd=ROOT,
            )
            completed = subprocess.run(
                (
                    "node",
                    str(I18N_CLI),
                    "extract",
                    "--project-root",
                    str(repository_root),
                    "--source-root",
                    str(source_root),
                ),
                check=True,
                capture_output=True,
                cwd=ROOT,
                text=True,
            )
            generated_manifest = json.loads(
                output.read_text(encoding="utf-8")
            )
            cli_manifest = json.loads(completed.stdout)

        self.assertEqual(generated_manifest, cli_manifest)

    def test_generator_merges_compatible_singular_and_plural_calls(self) -> None:
        """The same gettext key may serve ``t`` and ``tn`` callers."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            source_root = repository_root / "src"
            source_root.mkdir()
            output = repository_root / "messages.json"
            (source_root / "component.ts").write_text(
                'this.i18n.t("item");\n'
                'this.i18n.tn("item", "items", count);\n',
                encoding="utf-8",
            )

            subprocess.run(
                (
                    "node",
                    str(GENERATOR),
                    "--repository-root",
                    str(repository_root),
                    "--source-root",
                    str(source_root),
                    "--output",
                    str(output),
                ),
                check=True,
                cwd=ROOT,
            )
            messages = json.loads(output.read_text(encoding="utf-8"))["messages"]

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["id"], "item")
        self.assertEqual(messages[0]["plural"], "items")
        self.assertEqual(len(messages[0]["locations"]), 2)

    def test_generator_rejects_conflicting_plural_forms(self) -> None:
        """One gettext key cannot declare two different plural source IDs."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            source_root = repository_root / "src"
            source_root.mkdir()
            (source_root / "component.ts").write_text(
                'this.i18n.tn("item", "items", count);\n'
                'this.i18n.tn("item", "item records", count);\n',
                encoding="utf-8",
            )

            completed = subprocess.run(
                (
                    "node",
                    str(GENERATOR),
                    "--repository-root",
                    str(repository_root),
                    "--source-root",
                    str(source_root),
                    "--output",
                    str(repository_root / "messages.json"),
                ),
                check=False,
                capture_output=True,
                cwd=ROOT,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("has conflicting plural forms", completed.stderr)

    def test_catalog_translation_uses_manifest_instead_of_a_manual_id_list(self) -> None:
        """The runtime helper translates every generated singular identity."""

        class Catalog:
            """Minimal Babel-compatible catalog used by this unit test."""

            def gettext(self, message: str) -> str:
                """Mark translated messages without owning their identities."""
                return f"translated:{message}"

        translated = frontend_catalog_messages(Catalog())

        self.assertEqual(
            set(translated),
            {message.catalog_key for message in oldman_web_messages()},
        )
        self.assertEqual(
            translated["Loading..."],
            "translated:Loading...",
        )

    def test_browser_catalog_preserves_the_gettext_plural_rule(self) -> None:
        """Admin bootstrap and language endpoints must retain plural selection."""

        class Catalog:
            """Minimal gettext catalog with one compiled plural header."""

            _info = {
                "plural-forms": (
                    "nplurals=3; "
                    "plural=(n%10==1 ? 0 : n%10>=2 ? 1 : 2);"
                )
            }

            def gettext(self, message: str) -> str:
                """Return source strings because this test targets metadata."""
                return message

        payload = frontend_catalog_payload(Catalog(), "ru")

        self.assertEqual(payload["locale"], "ru")
        self.assertEqual(
            payload["pluralRule"],
            "(n%10==1 ? 0 : n%10>=2 ? 1 : 2)",
        )
        messages = payload["messages"]
        self.assertIsInstance(messages, dict)
        assert isinstance(messages, dict)
        self.assertEqual(
            set(messages),
            {message.catalog_key for message in oldman_web_messages()},
        )

    def test_project_browser_catalog_filters_unified_messages_po(self) -> None:
        """Static JSON keeps project/framework frontend IDs but no backend IDs."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            source_root = project_root / "frontend" / "src"
            source_root.mkdir(parents=True)
            (source_root / "main.ts").write_text(
                'i18n.tc("button", "Open");\n'
                'i18n.tn("{count} file", "{count} files", count);\n',
                encoding="utf-8",
            )
            po_file = project_root / "messages.po"
            po_file.write_text(
                '\n'.join(
                    (
                        'msgid ""',
                        'msgstr ""',
                        '"Language: zh_Hans\\n"',
                        '"Plural-Forms: nplurals=1; plural=0;\\n"',
                        '',
                        'msgctxt "button"',
                        'msgid "Open"',
                        'msgstr "打开"',
                        '',
                        'msgid "{count} file"',
                        'msgid_plural "{count} files"',
                        'msgstr[0] "{count} 个文件"',
                        '',
                        'msgid "Loading..."',
                        'msgstr "正在加载..."',
                        '',
                        'msgid "Backend secret"',
                        'msgstr "后端专用"',
                    )
                ),
                encoding="utf-8",
            )

            payload = compile_project_frontend_catalog(
                project_root,
                po_file,
                fallback_locale="zh_Hans",
                compiler_command=("node", str(I18N_CLI)),
            )

        self.assertEqual(payload["locale"], "zh_Hans")
        self.assertEqual(payload["pluralRule"], "0")
        messages = payload["messages"]
        self.assertIsInstance(messages, dict)
        assert isinstance(messages, dict)
        self.assertEqual(messages["button\x04Open"], "打开")
        self.assertEqual(messages["{count} file"], ["{count} 个文件"])
        self.assertEqual(messages["Loading..."], "正在加载...")
        self.assertNotIn("Backend secret", messages)

    def test_browser_catalog_filter_rejects_invalid_compiler_payload(self) -> None:
        """Malformed compiler output cannot silently become a browser catalog."""
        with self.assertRaisesRegex(ValueError, "invalid value"):
            filter_frontend_catalog_payload(
                {
                    "locale": "en",
                    "messages": {"Loading...": [1]},
                },
                oldman_web_messages(),
            )


if __name__ == "__main__":
    unittest.main()
