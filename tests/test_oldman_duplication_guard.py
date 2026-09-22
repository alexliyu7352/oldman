"""The duplication guard, and the framework's own Admin-versus-web boundary."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from oldman.testing.duplication import (
    duplicate_functions,
    forbidden_attributes,
    forbidden_imports,
    identical_files,
    iter_python_files,
)

ROOT = Path(__file__).resolve().parents[1]


def write(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return path


class UnreadableSourceTest(unittest.TestCase):
    """守卫的职责是报告重复，不是替别人的编码决定：读不了的文件跳过，不是让整轮检查崩掉。"""

    def test_a_non_utf8_source_is_skipped_by_every_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-duplication-") as directory:
            root = Path(directory)
            (root / "left").mkdir()
            (root / "right").mkdir()
            (root / "left" / "legacy.py").write_bytes("# -*- coding: latin-1 -*-\nname = 'caf\xe9'\n".encode("latin-1"))
            write(root / "right", "other.py", "x = 1\n")

            self.assertEqual([], duplicate_functions(root / "left", root / "right"))
            self.assertEqual([], forbidden_imports(root / "left", modules=("os",)))
            self.assertEqual([], forbidden_attributes(root / "left", attributes=("app.ext",)))


class DuplicateFunctionTest(unittest.TestCase):
    def test_same_name_and_same_body_is_reported_once_with_its_size(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-duplication-") as directory:
            root = Path(directory)
            body = """
            def build_url(name, base):
                \"\"\"One docstring.\"\"\"
                cleaned = name.strip("/")
                if not cleaned:
                    return base
                joined = f"{base}/{cleaned}"
                return joined
            """
            write(root / "left", "module.py", body)
            # A different docstring and comments must not hide the copy.
            write(root / "right", "other.py", body.replace("One docstring.", "Another docstring."))

            duplicates = duplicate_functions(root / "left", root / "right", min_lines=6)

            self.assertEqual(["build_url"], [item.name for item in duplicates])
            self.assertEqual(7, duplicates[0].lines)
            self.assertIn("build_url", duplicates[0].describe())

    def test_a_different_body_or_a_short_function_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-duplication-") as directory:
            root = Path(directory)
            write(
                root / "left",
                "module.py",
                """
            def build_url(name, base):
                cleaned = name.strip("/")
                if not cleaned:
                    return base
                joined = f"{base}/{cleaned}"
                return joined

            def small(value):
                return value
            """,
            )
            write(
                root / "right",
                "other.py",
                """
            def build_url(name, base):
                return f"{base}/{name}"

            def small(value):
                return value
            """,
            )

            self.assertEqual([], duplicate_functions(root / "left", root / "right", min_lines=6))

    def test_excluded_names_and_directories_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-duplication-") as directory:
            root = Path(directory)
            body = """
            def main():
                first = 1
                second = 2
                third = first + second
                fourth = third * 2
                return fourth
            """
            write(root / "left", "module.py", body)
            write(root / "right", "other.py", body)
            write(root / "left", "migrations/0001_initial.py", body)

            self.assertEqual([], duplicate_functions(root / "left", root / "right", min_lines=6, exclude_names=("main",)))
            self.assertNotIn("0001_initial.py", [path.name for path in iter_python_files(root / "left")])


class IdenticalFileTest(unittest.TestCase):
    def test_only_same_named_files_with_identical_bytes_are_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-duplication-") as directory:
            root = Path(directory)
            payload = "# helper\n" + "value = 1\n" * 40
            write(root / "left", "scripts/helper.py", payload)
            write(root / "right", "tools/helper.py", payload)
            write(root / "left", "scripts/other.py", payload + "extra = 2\n")

            matches = identical_files(root / "left", root / "right", suffixes=(".py",))

            self.assertEqual(["helper.py"], [item.left.name for item in matches])
            self.assertIn("helper.py", matches[0].describe())

    def test_small_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-duplication-") as directory:
            root = Path(directory)
            write(root / "left", "a.py", "x = 1\n")
            write(root / "right", "a.py", "x = 1\n")

            self.assertEqual([], identical_files(root / "left", root / "right", suffixes=(".py",)))


class ForbiddenReferenceTest(unittest.TestCase):
    def test_private_module_imports_are_reported_unless_allowed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-duplication-") as directory:
            root = Path(directory)
            write(
                root,
                "views.py",
                """
            from oldman.apps.admin.site import render_admin_template
            from oldman.apps.admin import AdminSite
            from oldman.web.auth import login_user
            import oldman.apps.admin.model_admin
            """,
            )

            reported = forbidden_imports(root, modules=("oldman.apps.admin",), allowed_names=("AdminSite",))

            self.assertEqual(
                ["from oldman.apps.admin.site import render_admin_template", "import oldman.apps.admin.model_admin"],
                [item.text for item in reported],
            )
            self.assertIn("views.py:1", reported[0].describe(root=root))

    def test_attribute_chains_are_matched_at_their_tail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-duplication-") as directory:
            root = Path(directory)
            write(
                root,
                "views.py",
                """
            def render(request):
                environment = request.app.ext.environment
                other = request.app.ctx.tasks
                return environment, other
            """,
            )

            reported = forbidden_attributes(root, attributes=("app.ext.environment",))

            self.assertEqual(["app.ext.environment"], [item.text for item in reported])


class FrameworkBoundaryTest(unittest.TestCase):
    """内置 Admin 不应该和 web/auth 层维护同一段实现。"""

    def test_the_admin_app_shares_implementations_instead_of_copying_them(self) -> None:
        duplicates = [
            item.describe(left_root=ROOT, right_root=ROOT)
            for item in duplicate_functions(ROOT / "oldman" / "apps" / "admin", ROOT / "oldman" / "web", min_lines=6)
        ]
        duplicates += [
            item.describe(left_root=ROOT, right_root=ROOT)
            for item in duplicate_functions(ROOT / "oldman" / "apps" / "admin", ROOT / "oldman" / "auth", min_lines=6)
        ]

        self.assertEqual([], duplicates)

    def test_no_framework_file_is_a_byte_copy_of_another_one(self) -> None:
        matches = [
            item.describe(left_root=ROOT, right_root=ROOT)
            for item in identical_files(ROOT / "oldman" / "apps" / "admin", ROOT / "oldman" / "web", suffixes=(".py", ".html"))
        ]

        self.assertEqual([], matches)


if __name__ == "__main__":
    unittest.main()


class ConvergedImplementationTest(unittest.TestCase):
    """Three things this repository implemented twice, and the JSON parser on the security path.

    The duplication guard already in this file catches copy-pasted Python functions. It was
    green on all of these: one pair was a protected method copied into another package's
    TypeScript, one was two private methods with the same body in different classes, and the
    JSON case is not duplication at all but four libraries doing one job.
    """

    ROOT = Path(__file__).resolve().parents[1]

    def test_the_child_logging_context_is_resolved_in_one_place(self) -> None:
        """The executor and the task manager had byte-identical private copies."""
        from oldman.logging import resolve_child_logging_context

        self.assertTrue(callable(resolve_child_logging_context))

        bodies = []
        for relative in ("processes/executor.py", "tasks/manager.py"):
            source = (self.ROOT / "oldman" / relative).read_text(encoding="utf-8")
            self.assertIn("resolve_child_logging_context", source, f"{relative} does not use the shared resolver")
            self.assertNotIn("runtime.child_context", source, f"{relative} still resolves the context itself")
            bodies.append(source)
        self.assertEqual(2, len(bodies))

    def test_escape_html_exists_once_and_is_exported(self) -> None:
        """The copy existed because the original was protected, so exporting it is the fix."""
        frontend = self.ROOT / "frontend"
        helpers = (frontend / "packages/oldman-web/src/core/dom/helpers.ts").read_text(encoding="utf-8")
        self.assertIn("export function escapeHtml(", helpers)

        topbar = (frontend / "packages/oldman-web/src/dashboard/topbar.ts").read_text(encoding="utf-8")
        self.assertNotIn("protected escapeHtml", topbar)

        admin = (frontend / "apps/admin/src/main.ts").read_text(encoding="utf-8")
        self.assertNotIn("function escapeHtml", admin, "the admin app declares its own copy again")
        self.assertIn("escapeHtml", admin, "the admin app should import the shared one")

    def test_ujson_is_gone_from_the_tree_and_the_dependencies(self) -> None:
        """ujson parsed the fingerprint payload - the one JSON input an attacker shapes."""
        offenders = [path.relative_to(self.ROOT) for path in (self.ROOT / "oldman").rglob("*.py") if "ujson" in path.read_text(encoding="utf-8")]
        self.assertEqual([], offenders)
        self.assertNotIn("ujson", (self.ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_the_fingerprint_payload_is_parsed_by_orjson(self) -> None:
        import orjson

        from oldman.web.security import decryptors

        self.assertIs(orjson, decryptors.orjson)
