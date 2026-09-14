"""Documentation-contract checks for the frozen Native Cache scope."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CacheDocumentationTest(unittest.TestCase):
    """Require useful definition-level documentation in the Cache core."""

    FILES = (
        ROOT / "oldman/cache/base.py",
        ROOT / "oldman/cache/exceptions.py",
        ROOT / "oldman/cache/images.py",
        ROOT / "oldman/cache/two_level.py",
        ROOT / "oldman/cache/utils.py",
        ROOT / "oldman/cache/backends/memory.py",
        ROOT / "oldman/cache/backends/redis.py",
        ROOT / "oldman/serializers/cache.py",
    )

    def test_every_class_function_and_method_has_a_docstring(self) -> None:
        """List every undocumented class, function, method, and nested operation."""
        missing: list[str] = []
        for path in self.FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if ast.get_docstring(node, clean=False) is None:
                        missing.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
