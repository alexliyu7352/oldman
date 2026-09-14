"""Catalog command integration tests."""

from __future__ import annotations

import tempfile
import unittest
from importlib.resources import as_file, files
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po, write_po

from oldman.i18n.commands import (
    FRAMEWORK_BABEL_CFG,
    KEYWORDS,
    _extract_catalog,
    _merge_catalogs,
)
from oldman.i18n.frontend import (
    FrontendMessage,
    FrontendMessageLocation,
    extract_project_frontend_messages,
)

ROOT = Path(__file__).resolve().parents[1]
I18N_CLI = (
    ROOT
    / "frontend"
    / "packages"
    / "oldman-web"
    / "bin"
    / "oldman-web-i18n.mjs"
)


class OldmanI18nCommandsTest(unittest.TestCase):
    """Keep packaged framework extraction independent from project settings."""

    def test_framework_admin_catalog_can_be_extracted_and_merged(self) -> None:
        """Use the package parent as cwd so ``oldman.logging`` cannot shadow stdlib."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            framework_pot = temporary_root / "framework.pot"
            project_pot = temporary_root / "project.pot"
            merged_pot = temporary_root / "messages.pot"

            with project_pot.open("wb") as stream:
                write_po(stream, Catalog(project="test"))

            with as_file(files("oldman")) as framework_root:
                _extract_catalog(
                    config=f"{framework_root.name}/{FRAMEWORK_BABEL_CFG}",
                    output=framework_pot,
                    source=framework_root.name,
                    keywords=KEYWORDS,
                    cwd=framework_root.parent,
                )
            _merge_catalogs(project_pot, framework_pot, merged_pot)

            with merged_pot.open("rb") as stream:
                messages = [message for message in read_po(stream) if message.id]

        admin_locations = [path for message in messages for path, _line in message.locations if path.startswith("oldman/apps/admin/")]
        cli_locations = [
            path
            for message in messages
            for path, _line in message.locations
            if path.startswith("oldman/cli/")
        ]
        frontend_locations = [
            path
            for message in messages
            for path, _line in message.locations
            if path.startswith("frontend/")
        ]
        self.assertTrue(admin_locations)
        self.assertTrue(cli_locations)
        self.assertTrue(frontend_locations)
        self.assertTrue(any(message.id == "Loading..." for message in messages))
        self.assertTrue(any(message.id == "Service commands" for message in messages))
        authentication = next(message for message in messages if message.id == "Authentication")
        self.assertIn("oldman/auth/apps.py", [path for path, _line in authentication.locations])
        self.assertFalse(
            any(".test." in path or ".spec." in path for path in frontend_locations)
        )
        self.assertFalse(any(path.startswith("oldman/oldman/") for path in admin_locations))

    def test_project_frontend_ast_messages_merge_into_messages_pot(self) -> None:
        """Project TypeScript context and plural IDs join the Babel catalog."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            source_root = project_root / "frontend" / "src"
            source_root.mkdir(parents=True)
            (source_root / "messages.ts").write_text(
                '\n'.join(
                    (
                        'i18n.t("Save");',
                        'i18n.tc("button", "Open");',
                        'i18n.tn("{count} file", "{count} files", count);',
                        'i18n.tnc("menu", "{count} item", "{count} items", count);',
                    )
                ),
                encoding="utf-8",
            )
            frontend_messages = extract_project_frontend_messages(
                project_root,
                compiler_command=("node", str(I18N_CLI)),
            )
            project_pot = project_root / "project.pot"
            framework_pot = project_root / "framework.pot"
            output = project_root / "messages.pot"
            with project_pot.open("wb") as stream:
                write_po(stream, Catalog(project="project"))
            with framework_pot.open("wb") as stream:
                write_po(stream, Catalog(project="framework"))

            _merge_catalogs(
                project_pot,
                framework_pot,
                output,
                project_frontend_messages=frontend_messages,
            )
            with output.open("rb") as stream:
                catalog = read_po(stream)

        identities = {
            (message.context, message.id)
            for message in catalog
            if message.id
        }
        self.assertIn((None, "Save"), identities)
        self.assertIn(("button", "Open"), identities)
        self.assertIn(
            (None, ("{count} file", "{count} files")),
            identities,
        )
        self.assertIn(
            ("menu", ("{count} item", "{count} items")),
            identities,
        )

    def test_frontend_extraction_skips_absent_source_and_preserves_ast_error(self) -> None:
        """API projects need no Node, while invalid frontend IDs keep locations."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            self.assertEqual(
                (),
                extract_project_frontend_messages(project_root),
            )

            source_root = project_root / "frontend" / "src"
            source_root.mkdir(parents=True)
            (source_root / "broken.ts").write_text(
                "i18n.t(message);\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                RuntimeError,
                r"frontend/src/broken\.ts:1:.*static string literal",
            ):
                extract_project_frontend_messages(
                    project_root,
                    compiler_command=("node", str(I18N_CLI)),
                )

    def test_merge_rejects_cross_source_plural_drift(self) -> None:
        """Python and frontend cannot assign different plurals to one key."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_pot = root / "project.pot"
            framework_pot = root / "framework.pot"
            output = root / "messages.pot"
            project_catalog = Catalog(project="project")
            project_catalog.add(("item", "items"))
            with project_pot.open("wb") as stream:
                write_po(stream, project_catalog)
            with framework_pot.open("wb") as stream:
                write_po(stream, Catalog(project="framework"))
            frontend_message = FrontendMessage(
                id="item",
                context=None,
                plural="item records",
                locations=(
                    FrontendMessageLocation(
                        path="frontend/src/items.ts",
                        line=1,
                    ),
                ),
            )

            with self.assertRaisesRegex(ValueError, "conflicting plural"):
                _merge_catalogs(
                    project_pot,
                    framework_pot,
                    output,
                    project_frontend_messages=(frontend_message,),
                )


if __name__ == "__main__":
    unittest.main()
