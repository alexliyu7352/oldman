"""render_fragment: one fragment through the app's installed environment, request included."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from jinja2 import DictLoader, Environment
from markupsafe import Markup

from oldman.web.template import render_fragment


def app_with(environment: Environment) -> SimpleNamespace:
    return SimpleNamespace(ext=SimpleNamespace(environment=environment))


class RenderFragmentTest(unittest.TestCase):
    def test_renders_with_the_request_in_context(self) -> None:
        environment = Environment(loader=DictLoader({"row.html": "<li>{{ name }} for {{ request.ctx.user }}</li>"}), enable_async=True)
        request = SimpleNamespace(app=app_with(environment), ctx=SimpleNamespace(user="ada"))

        html = asyncio.run(render_fragment(request, "row.html", name="Row"))

        self.assertIsInstance(html, Markup)
        self.assertEqual("<li>Row for ada</li>", str(html))

    def test_sync_environments_render_too(self) -> None:
        environment = Environment(loader=DictLoader({"row.html": "{{ request.label }}:{{ count }}"}))
        request = SimpleNamespace(app=app_with(environment), label="sync")

        html = asyncio.run(render_fragment(request, "row.html", count=3))

        self.assertEqual("sync:3", str(html))


    def test_a_framework_partial_renders_without_the_app_installing_loaders(self) -> None:
        """普通 web service 没装过模板 loader 时，也要能渲染框架自带的片段。"""
        environment = Environment(loader=DictLoader({"row.html": "<li></li>"}), enable_async=True)
        request = SimpleNamespace(app=app_with(environment), ctx=SimpleNamespace(csrf_token="t"))

        html = asyncio.run(
            render_fragment(
                request,
                "oldman/dashboard/components/modal_fragment.html",
                modal_id="probe",
                title="Probe",
                body=Markup("<p>body</p>"),
                component="modal",
                close_label="Close",
                managed=False,
                footer_close_label=None,
                dialog_class=None,
                hidden=False,
            )
        )

        self.assertIn("probe", str(html))


if __name__ == "__main__":
    unittest.main()
