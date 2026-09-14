"""Static-file discovery and collection contract tests."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oldman.web.staticfiles import (
    StaticSource,
    collect_project_static,
    collect_static,
    collection_manifest_path,
)
from oldman.web.staticfiles.collector import _resolve_public_root
from oldman.web.staticfiles.finders import StaticSourceFile


class OldmanStaticfilesCollectionTest(unittest.TestCase):
    """Verify deterministic collection without exposing package directories."""

    def test_first_source_wins_and_conflicts_are_reported(self) -> None:
        """Project assets override later framework assets by logical path."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            framework = root / "framework"
            output = root / "public"
            (project / "shared").mkdir(parents=True)
            (framework / "shared").mkdir(parents=True)
            (project / "shared" / "app.css").write_text(
                "project",
                encoding="utf-8",
            )
            (framework / "shared" / "app.css").write_text(
                "framework",
                encoding="utf-8",
            )
            (framework / "framework.js").write_text(
                "framework",
                encoding="utf-8",
            )

            result = collect_static(
                (
                    StaticSource("project", project),
                    StaticSource("framework", framework, package_owned=True),
                ),
                output,
            )

            self.assertEqual(
                "project",
                (output / "shared" / "app.css").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "framework",
                (output / "framework.js").read_text(encoding="utf-8"),
            )
            self.assertEqual(1, len(result.conflicts))
            self.assertEqual(
                "shared/app.css",
                result.conflicts[0].relative_path,
            )
            self.assertEqual("project", result.conflicts[0].winner)
            self.assertEqual("framework", result.conflicts[0].ignored)

    def test_equal_source_and_destination_preserves_project_overrides(self) -> None:
        """An equal static.dir/root only updates untouched managed assets."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / "static"
            framework = root / "framework"
            (framework / "oldman").mkdir(parents=True)
            (framework / "oldman" / "asset.txt").write_text(
                "version-one",
                encoding="utf-8",
            )
            source = StaticSource(
                "framework",
                framework,
                package_owned=True,
            )

            first = collect_project_static(
                project_directory=public,
                destination=public,
                packaged_sources=(source,),
            )
            managed_file = public / "oldman" / "asset.txt"
            self.assertEqual(1, first.copied)
            self.assertEqual("version-one", managed_file.read_text(encoding="utf-8"))

            managed_file.write_text("project-override", encoding="utf-8")
            (framework / "oldman" / "asset.txt").write_text(
                "version-two",
                encoding="utf-8",
            )
            second = collect_project_static(
                project_directory=public,
                destination=public,
                packaged_sources=(source,),
            )

            self.assertEqual(
                "project-override",
                managed_file.read_text(encoding="utf-8"),
            )
            self.assertEqual(1, len(second.conflicts))
            self.assertEqual("existing project file", second.conflicts[0].winner)

    def test_equal_root_updates_unchanged_managed_path_shapes(self) -> None:
        """Managed files may safely change between file and directory layouts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / "static"
            framework = root / "framework"
            framework.mkdir()
            source = StaticSource(
                "framework",
                framework,
                package_owned=True,
            )
            (framework / "asset").write_text("file", encoding="utf-8")
            collect_project_static(
                project_directory=public,
                destination=public,
                packaged_sources=(source,),
            )

            (framework / "asset").unlink()
            (framework / "asset").mkdir()
            (framework / "asset" / "child.txt").write_text(
                "child",
                encoding="utf-8",
            )
            collect_project_static(
                project_directory=public,
                destination=public,
                packaged_sources=(source,),
            )
            self.assertEqual(
                "child",
                (public / "asset" / "child.txt").read_text(encoding="utf-8"),
            )

            shutil.rmtree(framework / "asset")
            (framework / "asset").write_text("file-again", encoding="utf-8")
            collect_project_static(
                project_directory=public,
                destination=public,
                packaged_sources=(source,),
            )
            self.assertEqual(
                "file-again",
                (public / "asset").read_text(encoding="utf-8"),
            )

    def test_equal_root_project_ancestor_override_drops_managed_ownership(
        self,
    ) -> None:
        """A project ancestor override permanently leaves framework ownership."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / "static"
            framework = root / "framework"
            framework.mkdir()
            managed_file = framework / "asset"
            managed_file.write_text("managed-v1", encoding="utf-8")
            source = StaticSource(
                "framework",
                framework,
                package_owned=True,
            )
            collect_project_static(
                project_directory=public,
                destination=public,
                packaged_sources=(source,),
            )

            output_file = public / "asset"
            output_file.write_text("project-override", encoding="utf-8")
            managed_file.unlink()
            managed_file.mkdir()
            (managed_file / "child.txt").write_text(
                "managed-v2",
                encoding="utf-8",
            )
            collect_project_static(
                project_directory=public,
                destination=public,
                packaged_sources=(source,),
            )

            manifest = json.loads(
                collection_manifest_path(public).read_text(encoding="utf-8")
            )
            self.assertNotIn("asset", manifest["files"])

            output_file.write_text("managed-v1", encoding="utf-8")
            result = collect_project_static(
                project_directory=public,
                destination=public,
                packaged_sources=(source,),
            )

            self.assertTrue(output_file.is_file())
            self.assertEqual(
                "managed-v1",
                output_file.read_text(encoding="utf-8"),
            )
            self.assertFalse((output_file / "child.txt").exists())
            self.assertEqual(1, len(result.conflicts))
            self.assertEqual("existing project file", result.conflicts[0].winner)

    def test_clear_removes_stale_output_before_recollection(self) -> None:
        """Explicit clear removes stale output while ordinary collection does not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            output = root / "public"
            source_root.mkdir()
            source_file = source_root / "asset.txt"
            source_file.write_text("asset", encoding="utf-8")
            source = StaticSource("source", source_root)

            collect_static((source,), output)
            source_file.unlink()
            collect_static((source,), output)
            self.assertTrue((output / "asset.txt").exists())

            result = collect_static((source,), output, clear=True)

            self.assertFalse((output / "asset.txt").exists())
            self.assertEqual(1, result.removed)
            self.assertTrue(collection_manifest_path(output).is_file())

    def test_package_python_files_are_rejected(self) -> None:
        """A package source cannot accidentally publish executable Python."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            source_root.mkdir()
            (source_root / "leak.py").write_text("SECRET = True\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "contains Python file"):
                collect_static(
                    (
                        StaticSource(
                            "unsafe",
                            source_root,
                            package_owned=True,
                        ),
                    ),
                    root / "public",
                )

    def test_clear_preflight_failure_preserves_existing_output(self) -> None:
        """Invalid sources must fail before clear can remove a valid deployment."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            output = root / "public"
            source_root.mkdir()
            output.mkdir()
            existing = output / "existing.txt"
            existing.write_text("previous", encoding="utf-8")
            (source_root / "leak.py").write_text(
                "SECRET = True\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "contains Python file"):
                collect_static(
                    (
                        StaticSource(
                            "unsafe",
                            source_root,
                            package_owned=True,
                        ),
                    ),
                    output,
                    clear=True,
                )

            self.assertEqual(
                "previous",
                existing.read_text(encoding="utf-8"),
            )

    def test_collect_static_rejects_direct_source_output_overlap(self) -> None:
        """The public low-level collector must enforce the same overlap safety."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "public"
            source = output / "source"
            source.mkdir(parents=True)
            source_file = source / "project.css"
            source_file.write_text("project", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must not overlap"):
                collect_static(
                    (StaticSource("nested", source),),
                    output,
                    clear=True,
                )

            self.assertEqual(
                "project",
                source_file.read_text(encoding="utf-8"),
            )

    def test_filesystem_root_is_never_a_collection_destination(self) -> None:
        """Destination validation must reject a filesystem root unconditionally."""
        with self.assertRaisesRegex(ValueError, "filesystem root"):
            _resolve_public_root(Path(Path.cwd().anchor))

    def test_static_sources_reject_file_and_directory_symlinks(self) -> None:
        """Collection must never publish content reached through a source link."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text(
                "secret",
                encoding="utf-8",
            )

            for name, target_is_directory in (
                ("linked-directory", True),
                ("linked-file.txt", False),
            ):
                with self.subTest(name=name):
                    source = root / name
                    source.mkdir()
                    target = (
                        outside
                        if target_is_directory
                        else outside / "secret.txt"
                    )
                    (source / "link").symlink_to(
                        target,
                        target_is_directory=target_is_directory,
                    )
                    with self.assertRaisesRegex(
                        ValueError,
                        "contains symbolic link",
                    ):
                        collect_static(
                            (StaticSource(name, source),),
                            root / f"{name}-public",
                        )

    def test_project_collector_rejects_a_symlinked_source_root(self) -> None:
        """The high-level collector must not erase source-link identity."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "asset.txt").write_text("asset", encoding="utf-8")
            linked_source = root / "linked-source"
            linked_source.symlink_to(source, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                collect_project_static(
                    project_directory=linked_source,
                    destination=root / "public",
                    packaged_sources=(),
                )

    def test_losing_source_read_failure_preserves_existing_output(self) -> None:
        """Preflight must read duplicate losers before publishing any output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            output = root / "public"
            first.mkdir()
            second.mkdir()
            (first / "asset.txt").write_text("winner", encoding="utf-8")
            (second / "asset.txt").write_text("loser", encoding="utf-8")
            output.mkdir()
            existing = output / "existing.txt"
            existing.write_text("previous", encoding="utf-8")
            original_read_bytes = StaticSourceFile.read_bytes

            def read_or_fail(source_file: StaticSourceFile) -> bytes:
                if source_file.source_name == "second":
                    raise OSError("simulated losing source read failure")
                return original_read_bytes(source_file)

            with (
                patch.object(
                    StaticSourceFile,
                    "read_bytes",
                    read_or_fail,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "simulated losing source read failure",
                ),
            ):
                collect_static(
                    (
                        StaticSource("first", first),
                        StaticSource("second", second),
                    ),
                    output,
                    clear=True,
                )

            self.assertEqual("previous", existing.read_text(encoding="utf-8"))

    def test_explicit_empty_packaged_sources_remain_empty(self) -> None:
        """An empty source override must not silently restore framework assets."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            output = root / "public"
            project.mkdir()
            (project / "project.txt").write_text(
                "project",
                encoding="utf-8",
            )

            result = collect_project_static(
                project_directory=project,
                destination=output,
                packaged_sources=(),
            )

            self.assertEqual(1, result.copied)
            self.assertTrue((output / "project.txt").is_file())
            self.assertFalse((output / "oldman").exists())

    def test_file_directory_prefix_conflicts_use_source_priority(self) -> None:
        """A file/path prefix conflict must report a loser without partial output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            output = root / "public"
            first.mkdir()
            (second / "asset").mkdir(parents=True)
            (first / "asset").write_text("winner", encoding="utf-8")
            (second / "asset" / "child.txt").write_text(
                "ignored",
                encoding="utf-8",
            )

            result = collect_static(
                (
                    StaticSource("first", first),
                    StaticSource("second", second),
                ),
                output,
            )

            self.assertEqual(
                "winner",
                (output / "asset").read_text(encoding="utf-8"),
            )
            self.assertEqual(1, len(result.conflicts))
            self.assertEqual("asset/child.txt", result.conflicts[0].relative_path)
            self.assertEqual("first", result.conflicts[0].winner)
            self.assertEqual("second", result.conflicts[0].ignored)

    def test_publish_failure_restores_output_and_manifest(self) -> None:
        """A final manifest failure must restore the matching prior deployment."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            output = root / "public"
            source.mkdir()
            source_file = source / "asset.txt"
            source_file.write_text("old", encoding="utf-8")
            static_source = StaticSource("project", source)
            collect_static((static_source,), output)
            previous_manifest = collection_manifest_path(output).read_bytes()

            source_file.write_text("new", encoding="utf-8")

            def replace_or_fail(source_path: Path, destination: Path) -> None:
                if source_path.name == "manifest.json":
                    raise OSError("simulated manifest publication failure")
                source_path.replace(destination)

            with (
                patch(
                    "oldman.web.staticfiles.collector._replace_path",
                    side_effect=replace_or_fail,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "simulated manifest publication failure",
                ),
            ):
                collect_static((static_source,), output)

            self.assertEqual(
                "old",
                (output / "asset.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                previous_manifest,
                collection_manifest_path(output).read_bytes(),
            )

    def test_output_publish_failure_restores_output_and_manifest(self) -> None:
        """A staged-output failure must restore the matching prior deployment."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            output = root / "public"
            source.mkdir()
            source_file = source / "asset.txt"
            source_file.write_text("old", encoding="utf-8")
            static_source = StaticSource("project", source)
            collect_static((static_source,), output)
            previous_manifest = collection_manifest_path(output).read_bytes()
            source_file.write_text("new", encoding="utf-8")

            def replace_or_fail(source_path: Path, destination: Path) -> None:
                if source_path.name == "output":
                    raise OSError("simulated output publication failure")
                source_path.replace(destination)

            with (
                patch(
                    "oldman.web.staticfiles.collector._replace_path",
                    side_effect=replace_or_fail,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "simulated output publication failure",
                ),
            ):
                collect_static((static_source,), output)

            self.assertEqual(
                "old",
                (output / "asset.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                previous_manifest,
                collection_manifest_path(output).read_bytes(),
            )

    def test_collection_rejects_escaping_manifest_paths(self) -> None:
        """A tampered private manifest cannot delete files outside static.root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "public"
            output.mkdir()
            collection_manifest_path(output).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "files": {
                            "../outside.txt": {
                                "digest": "invalid",
                                "source": "invalid",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "invalid static collection manifest path",
            ):
                collect_static((), output, clear=True)

    def test_collection_rejects_invalid_manifest_digests_without_mutation(
        self,
    ) -> None:
        """Invalid managed digests cannot authorize deletion of project files."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "public"
            output.mkdir()
            project_file = output / "project.txt"
            project_file.write_text("project-owned", encoding="utf-8")
            manifest_path = collection_manifest_path(output)

            for invalid_digest in ("", "not-a-sha256", "A" * 64):
                with self.subTest(digest=invalid_digest):
                    manifest_path.write_text(
                        json.dumps(
                            {
                                "version": 1,
                                "files": {
                                    "project.txt": {
                                        "digest": invalid_digest,
                                        "source": "tampered",
                                    }
                                },
                            }
                        ),
                        encoding="utf-8",
                    )
                    previous_manifest = manifest_path.read_bytes()

                    with self.assertRaisesRegex(
                        RuntimeError,
                        "invalid static collection manifest entry",
                    ):
                        collect_project_static(
                            project_directory=output,
                            destination=output,
                            packaged_sources=(),
                            clear=True,
                        )

                    self.assertEqual(
                        "project-owned",
                        project_file.read_text(encoding="utf-8"),
                    )
                    self.assertEqual(
                        previous_manifest,
                        manifest_path.read_bytes(),
                    )

    def test_collection_rejects_overlapping_source_and_output_roots(self) -> None:
        """Clear mode must never remove a static source nested under its output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / "public"
            source = public / "source"
            source.mkdir(parents=True)
            source_file = source / "project.css"
            source_file.write_text("project", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must not overlap"):
                collect_project_static(
                    project_directory=source,
                    destination=public,
                    clear=True,
                    packaged_sources=(),
                )

            self.assertEqual(
                "project",
                source_file.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
