"""Dashboard shell macros that projects call from their own sidebar templates."""

from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from oldman.web.template import template_globals

TEMPLATES = Path(__file__).resolve().parents[1] / "oldman/web/templates"


def render(call: str) -> str:
    environment = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    template_globals(environment)["_"] = lambda message: message
    source = '{% from "oldman/dashboard/partials/shell.html" import sidebar_menu_item %}' + call
    return environment.from_string(source).render()


class SidebarMenuItemTest(unittest.TestCase):
    def test_a_link_that_leaves_the_shell_opens_as_a_whole_page(self) -> None:
        # The built-in Admin has its own layout and assets; swapped into the main Frame it would break.
        self.assertIn('href="/admin" data-turbo="false"', render('{{ sidebar_menu_item("/admin", "Admin", turbo=false) }}'))
        self.assertNotIn("data-turbo", render('{{ sidebar_menu_item("/users", "Users", active=true) }}'))


if __name__ == "__main__":
    unittest.main()
