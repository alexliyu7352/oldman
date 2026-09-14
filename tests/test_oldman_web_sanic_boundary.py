"""Public Oldman aliases for the single supported Sanic runtime."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import MappingProxyType, ModuleType
from unittest.mock import Mock

from sanic import Request, Sanic
from sanic.blueprints import Blueprint
from sanic.exceptions import Forbidden, NotFound
from sanic.response import BaseHTTPResponse, ResponseStream
from sanic.views import HTTPMethodView
from sanic_ext import render

import oldman.web as web

ROOT = Path(__file__).resolve().parents[1]


class OldmanWebSanicBoundaryTest(unittest.TestCase):
    """Verify public names hide imports without duplicating Sanic objects."""

    def test_public_types_are_canonical_sanic_objects(self) -> None:
        """Common framework types are aliases instead of handwritten Protocols."""
        self.assertIs(web.Request, Request)
        self.assertIs(web.WebApp, Sanic)
        self.assertIs(web.Response, BaseHTTPResponse)
        self.assertIs(web.StreamingResponse, ResponseStream)
        self.assertIs(web.StreamWriter, ResponseStream)
        self.assertIs(web.HTTPMethodView, HTTPMethodView)
        self.assertIs(web.Forbidden, Forbidden)
        self.assertIs(web.NotFound, NotFound)
        self.assertIs(web.render_template, render)
        self.assertIs(web.get_current_request.__self__, Request)
        self.assertIs(web.get_app.__self__, Sanic)

    def test_response_helpers_call_sanic_without_an_adapter(self) -> None:
        """Oldman response names preserve their small public conveniences."""
        headers = MappingProxyType({"X-Test": "value"})

        response = web.json_response({"ok": True}, headers=headers, status=201)
        no_content_type = web.text_response("", content_type=None)

        self.assertIsInstance(response, BaseHTTPResponse)
        self.assertEqual(201, response.status)
        self.assertEqual("value", response.headers["x-test"])
        self.assertIsNone(no_content_type.content_type)

    def test_lightweight_aggregate_does_not_import_db_components(self) -> None:
        """Importing common Web primitives cannot initialize component DB modules."""
        probe = (
            "import sys\n"
            "import oldman.web\n"
            "loaded = sorted(name for name in sys.modules "
            "if name.startswith('oldman.web.components'))\n"
            "if loaded:\n"
            "    raise SystemExit(','.join(loaded))\n"
        )

        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)

    def test_autodiscover_retains_oldman_blueprint_discovery(self) -> None:
        """The one custom routing helper remains owned by Oldman."""
        module = ModuleType("sample_views")
        module.__file__ = None
        blueprint = Blueprint("sample")
        module.__dict__["sample"] = blueprint
        app = Mock()
        app.__module__ = "sample"

        web.autodiscover(app, module)

        app.blueprint.assert_called_once_with(blueprint)

    def test_production_code_has_no_runtime_adapter_reference(self) -> None:
        """The deleted adapter cannot survive through a deferred production import."""
        references = []
        for path in (ROOT / "oldman").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "oldman.web.runtime" in source or "WebRuntimeAdapter" in source:
                references.append(path.relative_to(ROOT).as_posix())

        self.assertEqual([], references)


if __name__ == "__main__":
    unittest.main()
