"""Oldman native server-rendered form tests."""

from __future__ import annotations

import asyncio
import unittest

from wtforms import StringField

from oldman.web.components.forms import TailwindForm


class NativeProfileForm(TailwindForm):
    """Small form for native rendering tests."""

    name = StringField("Name")


class OldmanNativeFormNoFrontendTest(unittest.TestCase):
    """Verify forms remain usable without frontend runtime components."""

    def test_html_mode_can_render_without_frontend_component_hook(self) -> None:
        """Native HTML mode must not require data-om-component wiring."""
        html = str(
            asyncio.run(
                NativeProfileForm(csrf_token="csrf").render(
                    action="/profiles",
                    form_mode="html",
                    component_name=None,
                    submit_label="Save",
                )
            )
        )

        self.assertIn('action="/profiles"', html)
        self.assertIn('name="csrfmiddlewaretoken"', html)
        self.assertIn('name="name"', html)
        self.assertIn(">Save</button>", html)
        self.assertNotIn("data-om-component", html)

if __name__ == "__main__":
    unittest.main()
