"""Oldman package metadata tests."""

from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

from oldman.version import __VERSION__

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

REQUIRED_DEFAULT_DEPENDENCIES = {
    "aiohttp",
    "aiosqlite",
    "cryptography",
    "curl-cffi",
    "faststream",
    "httpx",
    "jinja2",
    "lxml",
    "markupsafe",
    "msgspec",
    "nats-py",
    "orjson",
    "pillow",
    "pydantic",
    "redis",
    "ruamel-yaml",
    "sanic",
    "sanic-ext",
    "sqlalchemy",
    "sqlmodel",
    "typer",
    "uuid6",
    "wtforms",
}
FORBIDDEN_SERVER_DB_DRIVERS = {"aiomysql", "asyncpg", "mysqlclient", "psycopg", "psycopg2"}
FORBIDDEN_EXTRAS = {"http_client", "cache", "web", "messaging", "media", "db", "dashboard", "admin"}


def load_pyproject() -> dict:
    """Load project metadata."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def dependency_name(requirement: str) -> str:
    """Return normalized package name from a requirement string."""
    head = requirement.split(";", 1)[0].strip()
    for separator in ("[", "<", ">", "=", "~", "!", " "):
        head = head.split(separator, 1)[0]
    return head.lower().replace("_", "-").replace(".", "-")


class OldmanPackageMetadataTest(unittest.TestCase):
    """Verify public package metadata boundaries."""

    def test_default_dependencies_match_framework_runtime_boundary(self) -> None:
        """Default dependencies include SQLite and exclude server database drivers."""
        dependencies = {dependency_name(item) for item in load_pyproject()["project"]["dependencies"]}

        self.assertTrue(REQUIRED_DEFAULT_DEPENDENCIES.issubset(dependencies), sorted(REQUIRED_DEFAULT_DEPENDENCIES - dependencies))
        self.assertTrue(FORBIDDEN_SERVER_DB_DRIVERS.isdisjoint(dependencies), sorted(FORBIDDEN_SERVER_DB_DRIVERS & dependencies))

    def test_package_does_not_publish_extras(self) -> None:
        """First public package has no extras split."""
        project = load_pyproject()["project"]

        self.assertNotIn("optional-dependencies", project)
        pyproject_text = PYPROJECT.read_text(encoding="utf-8")
        for extra in FORBIDDEN_EXTRAS:
            self.assertNotIn(f"oldman[{extra}]", pyproject_text)

    def test_console_script_and_build_backend_are_declared(self) -> None:
        """Wheel metadata exposes the Oldman CLI and hatchling backend."""
        pyproject = load_pyproject()

        self.assertEqual("oldman.cli:main", pyproject["project"]["scripts"]["oldman"])
        self.assertEqual("hatchling.build", pyproject["build-system"]["build-backend"])
        self.assertIn("hatchling", pyproject["build-system"]["requires"][0])

    def test_published_metadata_declares_readme_license_and_project_urls(self) -> None:
        """Package indexes must receive the public documentation and source links."""
        project = load_pyproject()["project"]

        self.assertEqual("README.md", project["readme"])
        self.assertEqual({"file": "LICENSE"}, project["license"])
        self.assertEqual(
            {
                "Documentation": "https://github.com/alexliyu7352/oldman#readme",
                "Homepage": "https://github.com/alexliyu7352/oldman",
                "Issues": "https://github.com/alexliyu7352/oldman/issues",
                "Repository": "https://github.com/alexliyu7352/oldman.git",
            },
            project["urls"],
        )

    def test_wheel_package_data_configuration_is_explicit(self) -> None:
        """Wheel config includes templates, admin static files and scaffolds."""
        wheel = load_pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]

        self.assertEqual(["oldman"], wheel["packages"])
        self.assertIn("**/__pycache__", wheel["exclude"])
        self.assertTrue((ROOT / "oldman" / "apps" / "admin" / "static").is_dir())
        self.assertTrue((ROOT / "oldman" / "apps" / "admin" / "templates").is_dir())
        self.assertTrue((ROOT / "oldman" / "scaffolds").is_dir())
        self.assertTrue((ROOT / "oldman" / "web" / "templates").is_dir())

    def test_public_metadata_has_no_private_index_or_internal_credentials(self) -> None:
        """Published pyproject must not contain private package index settings."""
        pyproject_text = PYPROJECT.read_text(encoding="utf-8")

        self.assertNotIn("tool.uv.index", pyproject_text)
        self.assertIsNone(re.search(r"(?<![\w.=<>~!])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", pyproject_text), "IPv4 literal in pyproject")
        self.assertIsNone(re.search(r"://[^/\s@]+:[^/\s@]+@", pyproject_text), "credentials embedded in a pyproject URL")

    def test_python_and_browser_runtime_versions_match_release_metadata(self) -> None:
        """Published metadata and runtime constants must describe the same release."""
        python_version = load_pyproject()["project"]["version"]
        root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        admin_package = json.loads((ROOT / "frontend" / "apps" / "admin" / "package.json").read_text(encoding="utf-8"))
        web_package = json.loads((ROOT / "frontend" / "packages" / "oldman-web" / "package.json").read_text(encoding="utf-8"))
        web_core = (ROOT / "frontend" / "packages" / "oldman-web" / "src" / "core" / "index.ts").read_text(encoding="utf-8")

        self.assertEqual(python_version, __VERSION__)
        self.assertEqual(python_version, root_package["version"])
        self.assertEqual(python_version, admin_package["version"])
        self.assertEqual(python_version, web_package["version"])
        self.assertIn(f'OLDMAN_WEB_VERSION = "{python_version}"', web_core)


if __name__ == "__main__":
    unittest.main()
