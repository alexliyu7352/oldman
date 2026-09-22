"""get_object_or_404 turns a missing primary key into a 404."""

from __future__ import annotations

import unittest
from typing import Any

from sanic.exceptions import NotFound

from oldman.web.shortcuts import get_object_or_404


class Project:
    __name__ = "Project"


class FakeSession:
    """Answers one session.get with the scripted row."""

    def __init__(self, row: Any) -> None:
        self.row = row
        self.calls: list[tuple[Any, Any]] = []

    async def get(self, model: Any, object_id: Any) -> Any:
        self.calls.append((model, object_id))
        return self.row


class GetObjectOr404Test(unittest.IsolatedAsyncioTestCase):
    async def test_it_returns_the_row_and_passes_the_key_through(self) -> None:
        row = object()
        session = FakeSession(row)

        self.assertIs(row, await get_object_or_404(session, Project, 7))
        self.assertEqual([(Project, 7)], session.calls)

    async def test_a_missing_row_raises_not_found_naming_the_model_and_key(self) -> None:
        with self.assertRaises(NotFound) as caught:
            await get_object_or_404(FakeSession(None), Project, 7)

        self.assertIn("Project 7 was not found", str(caught.exception))

    async def test_a_caller_message_replaces_the_default(self) -> None:
        with self.assertRaisesRegex(NotFound, "Stream profile was not found"):
            await get_object_or_404(FakeSession(None), Project, 7, message="Stream profile was not found")


if __name__ == "__main__":
    unittest.main()
