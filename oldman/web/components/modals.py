"""Render one dashboard Modal from Python instead of spelling out the template variables."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from oldman.i18n import gettext_lazy as _
from oldman.web.template import render_component_template_sync, render_fragment

MODAL_FRAGMENT_TEMPLATE = "oldman/dashboard/components/modal_fragment.html"


def modal_fragment_context(
    *,
    modal_id: str,
    title: Any,
    body: Markup | str,
    component: str = "modal",
    close_label: Any = _("Close"),
    managed: bool = False,
    footer_close_label: Any = None,
    dialog_class: str | None = None,
    hidden: bool = False,
) -> dict[str, Any]:
    """The variables `modal_fragment.html` expects, so callers name arguments instead of keys.

    `managed=False` is the fragment case: the markup is embedded in a page (a table cell, a panel)
    and opened by a `data-om-modal-target` button, not created and owned by the Modal manager.
    """
    return {
        "modal_id": modal_id,
        "modal_title": title,
        "modal_component": component,
        "modal_close_label": close_label,
        "modal_managed": managed,
        "modal_footer_close_label": footer_close_label,
        "modal_dialog_class": dialog_class,
        "modal_hidden": hidden,
        "modal_body": body,
    }


async def render_modal(request: Any, **options: Any) -> Markup:
    """Render one Modal through the request's environment; options are `modal_fragment_context`'s."""
    return await render_fragment(request, MODAL_FRAGMENT_TEMPLATE, **modal_fragment_context(**options))


def render_modal_sync(owner: Any, **options: Any) -> Markup:
    """Render one Modal from a synchronous context (a table cell callback); same options."""
    return render_component_template_sync(owner, MODAL_FRAGMENT_TEMPLATE, modal_fragment_context(**options))


__all__ = ["MODAL_FRAGMENT_TEMPLATE", "modal_fragment_context", "render_modal", "render_modal_sync"]
