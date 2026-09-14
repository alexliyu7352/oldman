"""Oldman frontend package boundary tests."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WEB_PACKAGE_ROOT = ROOT / "frontend" / "packages" / "oldman-web"
VERIFY_SCRIPT = ROOT / "scripts" / "verify-oldman-web-package.py"
CURRENT_RELEASE_WRAPPER = ROOT / "scripts" / "verify-current-release-oldman-web-package.py"
WORKSPACE_FILE = ROOT / "pnpm-workspace.yaml"
NO_FRONTEND_FORM_TEST = ROOT / "tests" / "test_oldman_native_form_no_frontend.py"
ICON_CLASS_PATTERN = re.compile(r"\b(?:ri|mdi|bx|bxs|bxl)-[a-z0-9-]+\b")
ICON_RULE_PATTERN = re.compile(r"^\.((?:ri|mdi|bx|bxs|bxl)-[a-z0-9-]+)::before\s*\{", re.MULTILINE)


def published_source_paths() -> dict[str, list[str]]:
    """Map every published oldman-web specifier to its workspace source entry."""
    package = json.loads((WEB_PACKAGE_ROOT / "package.json").read_text(encoding="utf-8"))
    paths: dict[str, list[str]] = {}
    for export_name, export_metadata in package["exports"].items():
        specifier = "oldman-web" if export_name == "." else f"oldman-web/{export_name.removeprefix('./')}"
        if export_name == "./package.json":
            source = "frontend/packages/oldman-web/package.json"
        else:
            target = export_metadata if isinstance(export_metadata, str) else export_metadata["import"]
            source = target.removeprefix("./dist/")
            if source.endswith(".js"):
                source = f"{source[:-3]}.ts"
            source = f"frontend/packages/oldman-web/src/{source}"
        paths[specifier] = [source]
    return paths


def collect_icon_classes(paths: tuple[Path, ...]) -> set[str]:
    names: set[str] = set()
    for source_root in paths:
        files = source_root.rglob("*") if source_root.is_dir() else (source_root,)
        for path in files:
            if not path.is_file() or ".test." in path.name or path.suffix not in {".html", ".py", ".tpl", ".ts"}:
                continue
            names.update(ICON_CLASS_PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return names


def generated_icon_classes(path: Path) -> set[str]:
    return set(ICON_RULE_PATTERN.findall(path.read_text(encoding="utf-8")))


def load_web_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_oldman_web_package", VERIFY_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load oldman-web verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class OldmanFrontendBoundaryTest(unittest.TestCase):
    """Verify the frontend package skeleton has enforceable boundaries."""

    def test_web_package_static_gate_passes(self) -> None:
        verifier = load_web_verifier()

        self.assertEqual([], verifier.verify_static_package())

    def test_workspace_resolution_matches_published_exports(self) -> None:
        """IDE 与 Vite 只能解析 package.json 已发布的精确入口。"""
        expected = published_source_paths()
        root_config = json.loads((ROOT / "tsconfig.base.json").read_text(encoding="utf-8"))
        root_paths = {
            name: targets
            for name, targets in root_config["compilerOptions"]["paths"].items()
            if name == "oldman-web" or name.startswith("oldman-web/")
        }
        self.assertEqual(expected, root_paths)
        self.assertFalse(any("*" in name for name in root_paths))

    def test_frontend_typecheck_configs_include_tests_but_build_excludes_them(self) -> None:
        """框架前端工程的 IDE/typecheck 配置覆盖测试，发布构建仍只处理 src。"""
        web_config_path = WEB_PACKAGE_ROOT / "tsconfig.json"
        self.assertTrue(web_config_path.is_file(), "oldman-web must provide the default IDE tsconfig.json")
        web_config = json.loads(web_config_path.read_text(encoding="utf-8"))
        admin_config = json.loads(
            (ROOT / "frontend" / "apps" / "admin" / "tsconfig.json").read_text(encoding="utf-8")
        )
        build_config = json.loads((WEB_PACKAGE_ROOT / "tsconfig.build.json").read_text(encoding="utf-8"))
        package = json.loads((WEB_PACKAGE_ROOT / "package.json").read_text(encoding="utf-8"))

        self.assertEqual("../../../tsconfig.base.json", web_config["extends"])
        for config in (web_config, admin_config):
            self.assertTrue(any(entry == "src" or entry.startswith("src/") for entry in config["include"]))
            self.assertFalse(any(".test." in entry for entry in config.get("exclude", [])))
        self.assertEqual(["src/**/*.ts"], build_config["include"])
        self.assertIn("src/**/*.test.ts", build_config["exclude"])
        self.assertEqual("tsc -p tsconfig.json --noEmit", package["scripts"]["typecheck"])

    def test_workspace_private_subpath_is_rejected_by_typecheck(self) -> None:
        """旧 wildcard 曾暴露的源码私有路径不能在 workspace 中绕过 exports。"""
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            probe_root = Path(tmp)
            (probe_root / "private-import.ts").write_text(
                'import { Page } from "oldman-web/core/page/page";\nvoid Page;\n',
                encoding="utf-8",
            )
            config = probe_root / "tsconfig.json"
            config.write_text(
                json.dumps(
                    {
                        "extends": "../tsconfig.base.json",
                        "compilerOptions": {"noEmit": True},
                        "include": ["private-import.ts"],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                ["pnpm", "--filter", "oldman-web", "exec", "tsc", "--project", config, "--pretty", "false"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        diagnostics = f"{completed.stdout}\n{completed.stderr}"
        self.assertNotEqual(0, completed.returncode, diagnostics)
        self.assertIn("TS2307", diagnostics)
        self.assertIn("oldman-web/core/page/page", diagnostics)

    def test_web_package_requires_explicit_release_artifacts(self) -> None:
        """npm 包门禁必须绑定同版本的显式 Python 与 npm 发布物。"""
        source = VERIFY_SCRIPT.read_text(encoding="utf-8")
        syntax = ast.parse(source)
        top_level_oldman_imports = [
            node
            for node in syntax.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and (
                isinstance(node, ast.ImportFrom)
                and (node.module == "oldman" or (node.module or "").startswith("oldman."))
                or isinstance(node, ast.Import)
                and any(alias.name == "oldman" or alias.name.startswith("oldman.") for alias in node.names)
            )
        ]
        command = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]["verify:web-package"]
        wrapper_source = CURRENT_RELEASE_WRAPPER.read_text(encoding="utf-8")

        self.assertEqual([], top_level_oldman_imports)
        self.assertIn('parser.add_argument("--wheel", required=True', source)
        self.assertIn('parser.add_argument("--npm-tarball", required=True', source)
        self.assertNotIn('environment["PYTHONPATH"]', source)
        self.assertEqual("uv run python3 scripts/verify-current-release-oldman-web-package.py", command)
        self.assertIn('(("pnpm", "build:python"), "build-python.log")', wrapper_source)
        self.assertIn('(("pnpm", "pack:web"), "pack-web.log")', wrapper_source)
        self.assertIn('from scripts.release_artifacts import authoritative_version, release_artifact_paths', wrapper_source)
        self.assertNotIn("*.whl", wrapper_source)
        self.assertNotIn("*.tgz", wrapper_source)
        self.assertIn("Evidence:", source)

    def test_web_package_clean_environment_removes_python_source_fallbacks(self) -> None:
        verifier = load_web_verifier()

        environment = verifier.clean_environment(
            {
                "PATH": "/bin",
                "PYTHONHOME": "/python",
                "PYTHONPATH": "/repo",
                "UV_PROJECT_ENVIRONMENT": "/repo/.venv",
                "VIRTUAL_ENV": "/repo/.venv",
            }
        )

        self.assertEqual("/bin", environment["PATH"])
        self.assertEqual("1", environment["PYTHONNOUSERSITE"])
        self.assertEqual("1", environment["CI"])
        for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
            self.assertNotIn(name, environment)

    def test_web_package_artifact_resolution_rejects_globs_and_missing_paths(self) -> None:
        verifier = load_web_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "explicit path"):
                verifier.resolve_artifact(str(root / "oldman-*.whl"), label="wheel", suffix=".whl")
            with self.assertRaisesRegex(RuntimeError, "not a readable"):
                verifier.resolve_artifact(str(root / "oldman.whl"), label="wheel", suffix=".whl")

            wheel = root / "oldman.whl"
            wheel.write_bytes(b"wheel")
            self.assertEqual(wheel.resolve(), verifier.resolve_artifact(str(wheel), label="wheel", suffix=".whl"))
            symlink = root / "linked.whl"
            symlink.symlink_to(wheel)
            with self.assertRaisesRegex(RuntimeError, "regular"):
                verifier.resolve_artifact(str(symlink), label="wheel", suffix=".whl")

    def test_web_package_rejects_mismatched_explicit_artifact_versions(self) -> None:
        verifier = load_web_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "oldman-1.2.3-py3-none-any.whl"
            with verifier.zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("oldman-1.2.3.dist-info/METADATA", "Name: oldman\nVersion: 1.2.3\n")
            npm_tarball = root / "oldman-web-9.9.9.tgz"
            package = json.dumps({"name": "oldman-web", "version": "9.9.9"}).encode()
            with tarfile.open(npm_tarball, "w:gz") as archive:
                metadata = tarfile.TarInfo("package/package.json")
                metadata.size = len(package)
                archive.addfile(metadata, io.BytesIO(package))

            result = verifier.main(
                [
                    "--wheel",
                    str(wheel),
                    "--npm-tarball",
                    str(npm_tarball),
                    "--evidence-dir",
                    str(root / "evidence"),
                ]
            )

            self.assertEqual(1, result)
            evidence = json.loads((root / "evidence" / "result.json").read_text(encoding="utf-8"))
            self.assertIn("Artifact version mismatch", evidence["errors"][0])

    def test_web_package_requires_the_selected_wheel_to_be_oldman(self) -> None:
        verifier = load_web_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "artifact.whl"
            with verifier.zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("other-1.0.dist-info/METADATA", "Name: other\nVersion: 1.0\n")
            with self.assertRaisesRegex(RuntimeError, "not the Oldman distribution"):
                verifier.wheel_identity(wheel)

            with verifier.zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("oldman-0.1.0.dist-info/METADATA", "Name: oldman\nVersion: 0.1.0\n")
            self.assertEqual({"name": "oldman", "version": "0.1.0"}, verifier.wheel_identity(wheel))

    def test_web_package_consumer_command_never_inherits_pythonpath(self) -> None:
        verifier = load_web_verifier()
        completed = subprocess.CompletedProcess(["probe"], 0, stdout="", stderr="")

        with patch.object(verifier.subprocess, "run", return_value=completed) as run:
            errors = verifier.run_consumer_command(
                ROOT,
                "probe",
                environment={"PATH": "/bin", "PYTHONPATH": "/repo", "PYTHONHOME": "/python"},
            )

        self.assertEqual([], errors)
        invoked_environment = run.call_args.kwargs["env"]
        self.assertNotIn("PYTHONPATH", invoked_environment)
        self.assertNotIn("PYTHONHOME", invoked_environment)

    def test_web_tarball_consumer_explicitly_typechecks_dashboard_options(self) -> None:
        """外部 consumer 必须只通过 tgz 声明检查 Dashboard 的公开配置类型。"""
        verifier = load_web_verifier()
        artifact = Path("/tmp/oldman-web-0.1.0.tgz")
        package = verifier.clean_consumer_package(artifact)

        self.assertEqual(
            [],
            verifier.clean_consumer_contract_errors(
                artifact,
                package,
                verifier.CLEAN_CONSUMER_TSCONFIG,
                verifier.CLEAN_CONSUMER_SOURCE,
                verifier.CLEAN_CONSUMER_COMMANDS,
            ),
        )
        self.assertEqual(f"file:{artifact.resolve()}", package["dependencies"]["oldman-web"])
        self.assertNotIn("extends", verifier.CLEAN_CONSUMER_TSCONFIG)
        compiler_options = verifier.CLEAN_CONSUMER_TSCONFIG["compilerOptions"]
        for fallback in ("baseUrl", "paths", "rootDirs", "typeRoots"):
            self.assertNotIn(fallback, compiler_options)
        for fragment in (
            "backToTopOptions: {",
            'defaultSidebarSize: "sm-hover"',
            'menuPanelSelector: "[data-consumer-menu-panel]"',
        ):
            self.assertIn(fragment, verifier.CLEAN_CONSUMER_SOURCE)
        self.assertEqual(
            ("pnpm", "exec", "tsc", "--noEmit", "--project", "tsconfig.json"),
            verifier.CLEAN_CONSUMER_COMMANDS[1],
        )

    def test_web_tarball_consumer_contract_rejects_typecheck_bypasses(self) -> None:
        """命令、配置或声明探针被弱化时，门禁必须先于 Vite 构建失败。"""
        verifier = load_web_verifier()
        artifact = Path("/tmp/oldman-web-0.1.0.tgz")
        package = verifier.clean_consumer_package(artifact)

        tampered_package = {**package, "dependencies": {"oldman-web": "workspace:*"}}
        tampered_tsconfig = {
            **verifier.CLEAN_CONSUMER_TSCONFIG,
            "extends": "../../../tsconfig.base.json",
            "compilerOptions": {
                **verifier.CLEAN_CONSUMER_TSCONFIG["compilerOptions"],
                "paths": {"oldman-web/*": ["frontend/packages/oldman-web/src/*"]},
            },
        }
        tampered_source = verifier.CLEAN_CONSUMER_SOURCE.replace(
            'menuPanelSelector: "[data-consumer-menu-panel]"',
            "",
        )
        tampered_commands = tuple(
            command for command in verifier.CLEAN_CONSUMER_COMMANDS if "tsc" not in command
        )

        errors = verifier.clean_consumer_contract_errors(
            artifact,
            tampered_package,
            tampered_tsconfig,
            tampered_source,
            tampered_commands,
        )

        self.assertTrue(any("exact selected npm tarball" in error for error in errors))
        self.assertTrue(any("workspace configuration" in error for error in errors))
        self.assertTrue(any("source fallback paths" in error for error in errors))
        self.assertTrue(any("menuPanelSelector" in error for error in errors))
        self.assertTrue(any("explicit tsc --noEmit" in error for error in errors))

    def test_dashboard_theme_adapters_are_stable_published_subpaths(self) -> None:
        """主题 adapter 必须可从 tarball 的公开子路径导入，不能依赖 workspace 内部路径。"""
        verifier = load_web_verifier()
        package = json.loads((WEB_PACKAGE_ROOT / "package.json").read_text(encoding="utf-8"))
        verify_source = VERIFY_SCRIPT.read_text(encoding="utf-8")
        expected = {
            "./dashboard/feedback": "./dist/dashboard/feedback.js",
            "./dashboard/modal": "./dist/dashboard/modal.js",
        }

        for subpath, import_target in expected.items():
            with self.subTest(subpath=subpath):
                self.assertIn(subpath, verifier.REQUIRED_EXPORTS)
                self.assertEqual(import_target, package["exports"][subpath]["import"])
                self.assertTrue(package["exports"][subpath]["types"].endswith(".d.ts"))
        for public_import in (
            'from "oldman-web/dashboard/feedback"',
            'from "oldman-web/dashboard/modal"',
        ):
            self.assertIn(public_import, verify_source)

    def test_admin_uses_dashboard_theme_adapters_without_private_copies(self) -> None:
        """Admin 只能组合同一组公开 Dashboard theme adapter。"""
        admin_source = (ROOT / "frontend" / "apps" / "admin" / "src" / "main.ts").read_text(encoding="utf-8")

        self.assertIn('oldman-web/dashboard/feedback', admin_source)
        self.assertIn('oldman-web/dashboard/modal', admin_source)
        self.assertIn('oldman-web/components/form', admin_source)
        self.assertNotIn('form-modal', admin_source)
        self.assertNotIn("class AdminModal", admin_source)
        self.assertNotIn("class AdminFormModal", admin_source)
        self.assertNotIn("class AdminFeedback", admin_source)

    def test_single_web_workspace_package_and_admin_app(self) -> None:
        workspace = WORKSPACE_FILE.read_text(encoding="utf-8")
        admin_package = json.loads((ROOT / "frontend" / "apps" / "admin" / "package.json").read_text(encoding="utf-8"))

        self.assertIn('frontend/packages/*', workspace)
        self.assertIn('frontend/apps/*', workspace)
        self.assertNotIn('examples/', workspace)
        self.assertEqual("oldman-admin", admin_package["name"])
        self.assertTrue(admin_package["private"])
        self.assertEqual(["oldman-web"], [path.name for path in (ROOT / "frontend" / "packages").iterdir() if path.is_dir()])

    def test_form_no_js_regression_test_does_not_depend_on_frontend_artifacts(self) -> None:
        source = NO_FRONTEND_FORM_TEST.read_text(encoding="utf-8")

        self.assertNotIn("frontend/", source)
        self.assertNotIn("oldman-web", source)
        self.assertIn("component_name=None", source)

    def test_root_entry_does_not_export_heavy_component_adapters(self) -> None:
        source = (WEB_PACKAGE_ROOT / "src" / "index.ts").read_text(encoding="utf-8")

        for token in ("apex-chart", "date-time-picker", "select"):
            self.assertNotIn(f"./components/{token}", source)

    def test_published_component_styles_have_a_compiler_and_side_effect_metadata(self) -> None:
        """A clean consumer must be able to bundle component SCSS imported by published JavaScript."""
        package = json.loads((WEB_PACKAGE_ROOT / "package.json").read_text(encoding="utf-8"))
        build_config = json.loads((WEB_PACKAGE_ROOT / "tsconfig.build.json").read_text(encoding="utf-8"))

        self.assertIn("sass", package["dependencies"])
        self.assertIn("./dist/**/*.scss", package["sideEffects"])
        self.assertIn("./src/**/*.scss", package["sideEffects"])
        self.assertTrue(build_config["compilerOptions"]["inlineSources"])

    def test_shared_tailwind_layer_has_single_framework_owner(self) -> None:
        """Admin 必须编译而不是复制框架样式。"""
        shared_css = (WEB_PACKAGE_ROOT / "src" / "styles" / "tailwind.css").read_text(encoding="utf-8")
        shared_icons = (WEB_PACKAGE_ROOT / "src" / "styles" / "icons.css").read_text(encoding="utf-8")
        admin_css = (ROOT / "frontend" / "apps" / "admin" / "src" / "admin.css").read_text(encoding="utf-8")

        for token in ("@theme", ".oldman-sidebar", ".oldman-topbar", ".om-button-primary", ".om-field", ".om-table"):
            self.assertIn(token, shared_css)
        self.assertIn('oldman-web/styles/tailwind.css', admin_css)
        self.assertIn('oldman-web/styles/icons.css', admin_css)
        self.assertNotIn(".oldman-sidebar {", admin_css)
        self.assertNotIn(".om-button-primary {", admin_css)
        self.assertNotIn(".ri-database-2-line::before", admin_css)
        self.assertIn(".ri-user-settings-line::before", shared_icons)
        self.assertIn(".ri-moon-line::before", shared_icons)
        self.assertNotIn(".ri-database-2-line::before", shared_icons)
        self.assertIn(".om-modal-header {\n    @apply border-b;", shared_css)
        self.assertIn(".om-modal-footer {\n    @apply border-t;", shared_css)
        self.assertIn(".om-modal-body {\n    @apply px-5 py-5;", shared_css)
        self.assertIn("[hidden] {\n    display: none !important;", shared_css)
        for utility in (
            "min-h-9",
            "text-end",
            "border-red-300",
            "focus:border-red-400",
            "focus:ring-red-200/60",
        ):
            self.assertIn(f'@source inline("{utility}");', shared_css)
        self.assertLess(len(admin_css.splitlines()), 80)
        self.assertNotIn('node-waves/dist/waves.min.css', shared_css)

    def test_published_tailwind_scans_compiled_runtime_javascript(self) -> None:
        shared_css = (WEB_PACKAGE_ROOT / "src" / "styles" / "tailwind.css").read_text(encoding="utf-8")

        self.assertIn('@source "../";', shared_css)

    def test_icon_generator_is_published_and_admin_owns_its_generated_icons(self) -> None:
        web_package = json.loads((WEB_PACKAGE_ROOT / "package.json").read_text(encoding="utf-8"))
        admin_package = json.loads((ROOT / "frontend" / "apps" / "admin" / "package.json").read_text(encoding="utf-8"))

        self.assertEqual("./bin/oldman-web-icons.mjs", web_package["bin"]["oldman-web-icons"])
        self.assertEqual("./bin/oldman-web-i18n.mjs", web_package["bin"]["oldman-web-i18n"])
        self.assertEqual(">=20", web_package["engines"]["node"])
        self.assertEqual(">=4.0.0 <5", web_package["peerDependencies"]["tailwindcss"])
        self.assertTrue((WEB_PACKAGE_ROOT / "LICENSE").is_file())
        for dependency in ("@iconify-json/bx", "@iconify-json/mdi", "@iconify-json/ri"):
            self.assertIn(dependency, web_package["dependencies"])
        self.assertIn("typescript", web_package["dependencies"])
        self.assertNotIn("typescript", web_package["devDependencies"])
        for package in (web_package, admin_package):
            self.assertIn("generate:icons", package["scripts"])
            self.assertIn("prebuild", package["scripts"])
            self.assertIn("pretypecheck", package["scripts"])

        shared_expected = collect_icon_classes(
            (
                WEB_PACKAGE_ROOT / "src" / "app",
                WEB_PACKAGE_ROOT / "src" / "components",
                WEB_PACKAGE_ROOT / "src" / "core",
                WEB_PACKAGE_ROOT / "src" / "dashboard",
                ROOT / "oldman" / "web" / "templates",
            )
        )
        admin_expected = collect_icon_classes(
            (
                ROOT / "frontend" / "apps" / "admin" / "src",
                ROOT / "oldman" / "apps" / "admin",
                ROOT / "oldman" / "auth",
            )
        ) - shared_expected
        self.assertEqual(shared_expected, generated_icon_classes(WEB_PACKAGE_ROOT / "src" / "styles" / "icons.css"))
        self.assertIn("ri-arrow-up-down-line", shared_expected)
        self.assertNotIn("ri-arrow-up-down-line", admin_expected)
        self.assertEqual(
            admin_expected,
            generated_icon_classes(ROOT / "frontend" / "apps" / "admin" / "src" / "generated" / "icons.css"),
        )
        self.assertNotIn("ri-24-hours-fill", shared_expected | admin_expected)

    def test_icon_generator_skips_dormant_theme_and_test_sources(self) -> None:
        generator = WEB_PACKAGE_ROOT / "bin" / "oldman-web-icons.mjs"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "components").mkdir(parents=True)
            (root / "src" / "theme").mkdir()
            (root / "src" / "components" / "active.ts").write_text('const icon = "ri-add-line";\n', encoding="utf-8")
            (root / "src" / "components" / "active.test.ts").write_text(
                'const testIcon = "ri-delete-bin-line";\n', encoding="utf-8"
            )
            (root / "src" / "theme" / "dormant.ts").write_text(
                'const dormantIcon = "ri-24-hours-fill";\n', encoding="utf-8"
            )
            output = root / "src" / "generated" / "icons.css"

            completed = subprocess.run(
                ["node", generator, "--output", output, "--source", root / "src"],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual({"ri-add-line"}, generated_icon_classes(output))


if __name__ == "__main__":
    unittest.main()
