"""Typed access to a Jinja environment's globals.

A leaf module, so that code inside ``oldman.web`` can use it without importing the whole
template package; ``oldman.web.template`` re-exports it as the public name.
"""

from collections.abc import MutableMapping
from typing import Any, cast

from jinja2 import Environment


def template_globals(environment: Environment) -> MutableMapping[str, Any]:
    """``environment.globals``, typed as the mapping of anything it is.

    Jinja assigns the attribute from its default namespace without an annotation, so type
    checkers infer a mapping whose values can only be ``range``, ``dict``, ``lipsum`` and the
    like, and refuse every function a project registers. Register globals through this.
    """
    return cast(MutableMapping[str, Any], environment.globals)
