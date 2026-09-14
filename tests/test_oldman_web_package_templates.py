"""Oldman Web package template tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jinja2 import DictLoader, Environment, nodes
from jinja2.ext import Extension

from oldman.web.package_data import package_template_dir
from oldman.web.template import build_template_loader, install_template_loaders, render_component_template_sync


class MarkerExtension(Extension):
    """Small extension proving sync overlays retain app-owned extensions."""

    tags = {"marker"}

    def parse(self, parser):
        token = next(parser.stream)
        return nodes.Output([nodes.Const(" EXT")], lineno=token.lineno)


class OldmanWebPackageTemplatesTest(unittest.TestCase):
    """Verify project templates override bundled framework templates."""

    def test_package_form_templates_are_bundled_under_oldman_web(self) -> None:
        """Framework form templates must be available without project copies."""
        template_dir = package_template_dir()

        self.assertTrue((template_dir / "oldman" / "forms" / "default" / "form.html").is_file())
        self.assertTrue((template_dir / "oldman" / "forms" / "default" / "field.html").is_file())
        self.assertTrue((template_dir / "oldman" / "dashboard" / "base.html").is_file())

    def test_dashboard_topbar_separates_user_notifications_and_activity(self) -> None:
        """Persistent notifications and local activity must expose disjoint DOM APIs."""
        environment = Environment(
            loader=build_template_loader(),
            autoescape=True,
        )
        environment.globals["_"] = lambda value: value
        rendered = environment.from_string(
            """
            {% from "oldman/dashboard/partials/topbar.html" import dashboard_topbar with context %}
            {{ dashboard_topbar(
                activity_notifications=activity,
                activity_href="/activity",
                user_notification_urls={"topbar": "/user-notifications/topbar", "center": "/user-notifications"}
            ) }}
            """
        ).render(
            activity=[
                SimpleNamespace(
                    tone="warning",
                    icon="ri-alert-line",
                    href="/activity/1",
                    title="Activity",
                    description="Local only",
                    time="Now",
                )
            ]
        )

        self.assertIn("data-om-user-notification-topbar", rendered)
        self.assertIn('data-om-topbar-url="/user-notifications/topbar"', rendered)
        self.assertIn('data-om-center-url="/user-notifications"', rendered)
        self.assertIn("data-om-user-notification-slot", rendered)
        self.assertGreaterEqual(rendered.count("data-om-user-notification-count"), 2)
        self.assertIn("data-om-activity-notifications", rendered)
        self.assertIn("data-om-activity-notification-item", rendered)
        self.assertIn("data-om-activity-notification-select", rendered)
        self.assertNotIn("data-om-user-notification-id", rendered)
        self.assertNotIn("data-om-user-notification-select", rendered)

    def test_project_template_loader_precedes_package_loader(self) -> None:
        """Project templates should override package templates by path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_template = Path(tmp_dir) / "oldman" / "forms" / "default" / "form.html"
            project_template.parent.mkdir(parents=True)
            project_template.write_text("PROJECT TEMPLATE", encoding="utf-8")
            environment = Environment(loader=build_template_loader(tmp_dir), enable_async=True)

            self.assertEqual(environment.get_template("oldman/forms/default/form.html").render(), "PROJECT TEMPLATE")

    def test_install_template_loaders_updates_existing_environment(self) -> None:
        """Sanic-Ext environments should receive the same project/package lookup."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_template = Path(tmp_dir) / "sample.html"
            project_template.write_text("sample", encoding="utf-8")
            environment = install_template_loaders(Environment(), tmp_dir)

            self.assertEqual(environment.get_template("sample.html").render(), "sample")

    def test_install_template_loaders_is_idempotent_for_the_same_environment(
        self,
    ) -> None:
        """Repeated installation must retain one loader and refresh filters only."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_template = Path(tmp_dir) / "shared.html"
            project_template.write_text("PROJECT", encoding="utf-8")
            environment = Environment(
                loader=DictLoader(
                    {
                        "shared.html": "ORIGINAL",
                        "original-only.html": "ORIGINAL ONLY",
                    }
                )
            )

            install_template_loaders(environment, tmp_dir)
            installed_loader = environment.loader
            environment.filters.pop("html_attrs")
            environment.globals.pop("_")

            install_template_loaders(environment, tmp_dir)

            self.assertIs(installed_loader, environment.loader)
            self.assertIn("html_attrs", environment.filters)
            self.assertIn("_", environment.globals)
            self.assertEqual("PROJECT", environment.get_template("shared.html").render())
            self.assertEqual(
                "ORIGINAL ONLY",
                environment.get_template("original-only.html").render(),
            )
            self.assertIsNotNone(
                environment.get_template("oldman/forms/default/form.html")
            )

    def test_sync_component_rendering_preserves_async_app_environment(self) -> None:
        """Sync component fragments must retain an async app's loader and customizations."""

        def suffix(value: object) -> str:
            return f"{value}-FILTER"

        environment = Environment(
            loader=DictLoader({"only-app.html": "{{ app_global|app_filter }}{% marker %}"}),
            enable_async=True,
            extensions=[MarkerExtension],
        )
        environment.globals["app_global"] = "CUSTOM"
        environment.filters["app_filter"] = suffix
        owner = SimpleNamespace(request=SimpleNamespace(app=SimpleNamespace(ext=SimpleNamespace(environment=environment))))

        rendered = render_component_template_sync(owner, "only-app.html", {})

        self.assertEqual("CUSTOM-FILTER EXT", rendered)


if __name__ == "__main__":
    unittest.main()
