"""Behavior tests for cold service discovery and explicit service loading."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_service(project_root: Path, relative_path: str, source: str) -> Path:
    """Write one temporary service fixture and return its path."""
    path = project_root / "services" / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _discovery_module(test_case: unittest.TestCase):
    """Import the new module while reporting a missing API as a test failure."""
    try:
        return importlib.import_module("oldman.runtime.discovery")
    except ModuleNotFoundError as exc:
        test_case.fail(f"cold service discovery API is missing: {exc}")


def _run_python(project_root: Path, source: str) -> subprocess.CompletedProcess[str]:
    """Run an isolated service-loading scenario in a fresh interpreter."""
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    python_paths = [str(PROJECT_ROOT)]
    if existing_path:
        python_paths.append(existing_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=project_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_oldman_help(project_root: Path) -> subprocess.CompletedProcess[str]:
    """Render root help in the same isolated project environment."""
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    python_paths = [str(PROJECT_ROOT)]
    if existing_path:
        python_paths.append(existing_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return subprocess.run(
        [sys.executable, "-m", "oldman.cli", "--help"],
        cwd=project_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


class ServiceDiscoveryTests(unittest.TestCase):
    """Verify discovery reads source without importing service modules."""

    def test_runtime_exports_cold_discovery_api(self) -> None:
        runtime = importlib.import_module("oldman.runtime")

        for name in (
            "ServiceDefinition",
            "discover_service_definitions",
            "get_service_definition",
            "load_service_class",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(runtime, name), name)

    def test_discovers_direct_modules_without_executing_them(self) -> None:
        discovery = _discovery_module(self)
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(
                project_root,
                "api.py",
                """
                raise RuntimeError("cold discovery imported api.py")

                class APIService(WebApplication):
                    pass
                """,
            )
            music_path = _write_service(
                project_root,
                "music_web.py",
                """
                class ServiceMixin:
                    pass

                class MusicWebService(
                    ServiceMixin,
                    SimpleApplication,
                ):
                    pass
                """,
            )
            _write_service(
                project_root,
                "__init__.py",
                'raise RuntimeError("package must not be imported")',
            )
            _write_service(project_root, "_helper.py", "this is not valid python")
            _write_service(
                project_root,
                "nested/worker.py",
                """
                class NestedWorker(SimpleApplication):
                    pass
                """,
            )

            definitions = discovery.discover_service_definitions(project_root)
            help_result = _run_oldman_help(project_root)

        self.assertEqual(list(definitions), ["api", "music_web"])
        self.assertEqual(definitions["api"].application_base, "web")
        self.assertEqual(definitions["music_web"].application_base, "simple")
        self.assertEqual(definitions["music_web"].module_name, "music_web")
        self.assertEqual(definitions["music_web"].module_path, music_path)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertNotIn("cold discovery imported", help_result.stderr)

    def test_rejects_invalid_public_module_name(self) -> None:
        discovery = _discovery_module(self)
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(
                project_root,
                "BadService.py",
                """
                class BadService(SimpleApplication):
                    pass
                """,
            )

            with self.assertRaisesRegex(ValueError, r"BadService\.py.*[a-z]"):
                discovery.discover_service_definitions(project_root)

    def test_rejects_an_indirect_application_base(self) -> None:
        discovery = _discovery_module(self)
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(
                project_root,
                "_base.py",
                """
                class ProjectApplication(SimpleApplication):
                    pass
                """,
            )
            _write_service(
                project_root,
                "worker.py",
                """
                from services._base import ProjectApplication

                class WorkerService(ProjectApplication):
                    pass
                """,
            )

            with self.assertRaisesRegex(ValueError, r"worker\.py.*direct"):
                discovery.discover_service_definitions(project_root)

    def test_rejects_multiple_application_classes(self) -> None:
        discovery = _discovery_module(self)
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(
                project_root,
                "api.py",
                """
                class PublicAPI(WebApplication):
                    pass

                class InternalAPI(WebApplication):
                    pass
                """,
            )

            with self.assertRaisesRegex(ValueError, r"api\.py.*exactly one"):
                discovery.discover_service_definitions(project_root)

    def test_rejects_a_class_with_both_application_bases(self) -> None:
        discovery = _discovery_module(self)
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(
                project_root,
                "api.py",
                """
                class AmbiguousService(WebApplication, SimpleApplication):
                    pass
                """,
            )

            with self.assertRaisesRegex(ValueError, r"api\.py.*more than one supported Application base"):
                discovery.discover_service_definitions(project_root)

    def test_get_service_definition_reports_an_unknown_name(self) -> None:
        discovery = _discovery_module(self)
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(
                project_root,
                "api.py",
                """
                class APIService(WebApplication):
                    pass
                """,
            )

            with self.assertRaisesRegex(ValueError, r"missing.*not found"):
                discovery.get_service_definition("missing", project_root)


class ServiceLoadingTests(unittest.TestCase):
    """Verify the warm path imports one module and enforces its contract."""

    def test_loads_only_the_selected_service_class(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(project_root, "__init__.py", "")
            _write_service(
                project_root,
                "worker.py",
                """
                from oldman.runtime import SimpleApplication

                class WorkerService(SimpleApplication):
                    def prepare(self):
                        pass

                    async def main(self):
                        pass
                """,
            )
            _write_service(
                project_root,
                "broken.py",
                """
                from oldman.runtime import SimpleApplication

                raise RuntimeError("unselected service was imported")

                class BrokenService(SimpleApplication):
                    def prepare(self):
                        pass

                    async def main(self):
                        pass
                """,
            )

            result = _run_python(
                project_root,
                """
                from pathlib import Path
                from oldman.runtime.discovery import (
                    discover_service_definitions,
                    load_service_class,
                )

                root = Path.cwd()
                definition = discover_service_definitions(root)["worker"]
                service_class = load_service_class(definition)
                assert service_class.__name__ == "WorkerService"
                assert service_class.__module__ == "services.worker"
                """,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_adapter_returns_cold_service_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(project_root, "__init__.py", "")
            _write_service(
                project_root,
                "worker.py",
                """
                from oldman.runtime import SimpleApplication

                class WorkerService(SimpleApplication):
                    def prepare(self):
                        pass

                    async def main(self):
                        pass
                """,
            )

            result = _run_python(
                project_root,
                """
                from oldman.cli._service_discovery import discover_services
                import sys

                services = discover_services()
                assert list(services) == ["worker"]
                assert services["worker"].module_name == "worker"
                assert services["worker"].application_base == "simple"
                assert "services.worker" not in sys.modules
                """,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_a_runtime_class_that_disagrees_with_static_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            service_path = _write_service(project_root, "__init__.py", "")
            service_path = _write_service(
                project_root,
                "worker.py",
                """
                from oldman.runtime import SimpleApplication

                class WorkerService(SimpleApplication):
                    def prepare(self):
                        pass

                    async def main(self):
                        pass
                """,
            )

            result = _run_python(
                project_root,
                f"""
                from pathlib import Path
                from oldman.runtime.discovery import ServiceDefinition, load_service_class

                definition = ServiceDefinition(
                    module_name="worker",
                    module_path=Path({str(service_path)!r}),
                    application_base="web",
                )
                try:
                    load_service_class(definition)
                except ValueError as exc:
                    assert "web" in str(exc)
                else:
                    raise AssertionError("runtime base mismatch was accepted")
                """,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_models_declared_during_service_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            _write_service(project_root, "__init__.py", "")
            _write_service(
                project_root,
                "worker.py",
                """
                from sqlalchemy.orm import Mapped, mapped_column

                from oldman.db.models import DatabaseModel
                from oldman.runtime import SimpleApplication

                class PrematureModel(DatabaseModel):
                    __tablename__ = "premature_service_model"

                    id: Mapped[int] = mapped_column(primary_key=True)

                class WorkerService(SimpleApplication):
                    def prepare(self):
                        pass

                    async def main(self):
                        pass
                """,
            )

            result = _run_python(
                project_root,
                """
                from pathlib import Path
                from oldman.runtime.discovery import (
                    discover_service_definitions,
                    load_service_class,
                )

                definition = discover_service_definitions(Path.cwd())["worker"]
                try:
                    load_service_class(definition)
                except RuntimeError as exc:
                    assert "premature_service_model" in str(exc)
                else:
                    raise AssertionError("service import created an unmanaged model")
                """,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
