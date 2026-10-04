"""Copying the framework's templates into a project: where they come from, what is asked, what is written."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from oldman.cli.scaffold import DatabaseChoice, ProjectType, start_project
from oldman.cli.templates import TemplateSource, apply_template_copy, framework_template_sources, plan_template_copy
from oldman.web.package_data import package_template_dir
from tests.test_oldman_cli_localization import cli_environment


class FrameworkTemplateSourcesTest(unittest.TestCase):
    def test_the_shared_templates_and_each_installed_framework_app_that_ships_some(self) -> None:
        """The Admin's templates only when the service installs the Admin; a project App's never."""
        with_admin = framework_template_sources(["oldman.auth", "oldman.apps.roles", "oldman.apps.admin", "apps.home"])
        without_admin = framework_template_sources(["oldman.auth", "oldman.apps.roles", "apps.home"])

        self.assertEqual(("oldman.web", "oldman.apps.admin"), tuple(source.package for source in with_admin))
        self.assertEqual(package_template_dir(), with_admin[0].root)
        self.assertTrue((with_admin[1].root / "admin").is_dir())
        self.assertEqual(("oldman.web",), tuple(source.package for source in without_admin))


class TemplateCopyPlanTest(unittest.TestCase):
    def test_new_files_are_copied_and_differing_ones_only_when_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            shared, admin, destination = root / "shared", root / "admin", root / "project" / "templates"
            for path, text in (
                (shared / "oldman" / "page.html", "page"),
                (shared / "oldman" / "same.html", "same"),
                (shared / "oldman" / "edited.html", "framework"),
                (admin / "admin" / "login.html", "login"),
                # The same path in a later source: the earlier one is the one a service finds, and the one copied.
                (admin / "oldman" / "page.html", "shadowed"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            (destination / "oldman").mkdir(parents=True)
            (destination / "oldman" / "same.html").write_text("same", encoding="utf-8")
            (destination / "oldman" / "edited.html").write_text("the project's", encoding="utf-8")

            plan = plan_template_copy((TemplateSource("oldman.web", shared), TemplateSource("oldman.apps.admin", admin)), destination)

            self.assertEqual(
                [Path("admin/login.html"), Path("oldman/page.html")],
                sorted(target.relative_to(destination) for _source, target in plan.new),
            )
            self.assertEqual([destination / "oldman" / "edited.html"], [target for _source, target in plan.changed])
            self.assertEqual(1, plan.unchanged)

            self.assertEqual(2, apply_template_copy(plan, overwrite=False))
            self.assertEqual("page", (destination / "oldman" / "page.html").read_text(encoding="utf-8"))
            self.assertEqual("the project's", (destination / "oldman" / "edited.html").read_text(encoding="utf-8"))
            self.assertEqual(3, apply_template_copy(plan, overwrite=True))
            self.assertEqual("framework", (destination / "oldman" / "edited.html").read_text(encoding="utf-8"))


class TemplatesCopyCommandTest(unittest.TestCase):
    """`./run.sh <web service> templates copy` in generated projects, through the real CLI entry point."""

    def run_cli(self, project: Path, *args: str, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "oldman.cli", *args],
            cwd=project,
            env={**cli_environment(project.parent / "config"), **environment},
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )

    def test_copies_into_the_project_and_asks_before_overwriting_what_it_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            previous = Path.cwd()
            os.chdir(parent)
            try:
                site = start_project("site", project_type=ProjectType.WEB, db=DatabaseChoice.SQLITE, admin=True)
                plain = start_project("plain", project_type=ProjectType.WEB, db=DatabaseChoice.SQLITE)
            finally:
                os.chdir(previous)
            for project in (site, plain):
                self.assertEqual(0, self.run_cli(project, "web", "settings", "sync").returncode)

            # The service is not started for it: loading its Apps twice would fail.
            first = self.run_cli(site, "web", "templates", "copy")
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            login = site / "templates" / "admin" / "login.html"
            self.assertTrue(login.is_file())
            self.assertTrue((site / "templates" / "oldman" / "dashboard" / "account" / "login.html").is_file())
            # The project's own templates are not the framework's and are left alone.
            self.assertIn("apps/home/views.py", (site / "templates" / "home" / "index.html").read_text(encoding="utf-8"))

            login.write_text("the project's own", encoding="utf-8")
            kept = self.run_cli(site, "web", "templates", "copy")
            self.assertEqual(0, kept.returncode, kept.stdout + kept.stderr)
            self.assertIn("admin/login.html", kept.stdout)
            self.assertEqual("the project's own", login.read_text(encoding="utf-8"))
            overwritten = self.run_cli(site, "web", "templates", "copy", OLDMAN_ANSWER_TEMPLATES_COPY_OVERWRITE="yes")
            self.assertEqual(0, overwritten.returncode, overwritten.stdout + overwritten.stderr)
            self.assertNotEqual("the project's own", login.read_text(encoding="utf-8"))

            # Without the Admin, none of its templates.
            self.assertEqual(0, self.run_cli(plain, "web", "templates", "copy").returncode)
            self.assertFalse((plain / "templates" / "admin").exists())
            self.assertTrue((plain / "templates" / "oldman").is_dir())


if __name__ == "__main__":
    unittest.main()
