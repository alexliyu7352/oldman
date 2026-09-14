"""Interactive shell backed by the public service bootstrap."""

from __future__ import annotations

import code
from pathlib import Path

from oldman.cli.settings import ensure_cwd_on_syspath
from oldman.runtime import ServiceBootstrapContext, bootstrap_service


def open_service_shell(
    service_module: str,
    *,
    config_file: Path | None = None,
) -> ServiceBootstrapContext:
    """Bootstrap one headless service context and open Python's interactive shell."""
    ensure_cwd_on_syspath()
    context = bootstrap_service(
        service_module,
        config_file=config_file,
    )
    code.interact(
        banner=(
            f"Oldman service {service_module!r} is bootstrapped. "
            "Available names: context, settings, apps."
        ),
        local={
            "context": context,
            "settings": context.settings,
            "apps": context.apps,
        },
    )
    return context


__all__ = ["open_service_shell"]
