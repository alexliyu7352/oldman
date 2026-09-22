"""Row-action modals of the shared user list: enable/disable and delete.

Both answer the Modal component's JSON shape (`title` plus `html`). A site passes the user it loaded
and the URL the form must post to; when the row is gone from the database the payload says so instead
of raising, because the browser has been holding that list for a while.

两个片段里都有 `{% csrf_token %}`，所以打开弹窗的那个路由必须带 `@add_csrf_token()`：没有的话表单
渲染出来是好的，用户点确认才拿到 403，页面上看不出原因。
"""

from __future__ import annotations

from typing import Any

from markupsafe import escape

from oldman.auth.base import AbstractUser
from oldman.i18n import gettext
from oldman.web.api import modal_not_found_response, modal_response
from oldman.web.template import render_fragment


async def user_status_modal_response(request: Any, user: AbstractUser | None, *, action: str):
    """Confirm switching one user between active and disabled; `action` takes the POST."""
    if user is None:
        return modal_not_found_response(gettext("Change Status", request=request), gettext("User not found.", request=request))
    target_active = not bool(user.is_active)
    modal_html = await render_fragment(
        request,
        "oldman/auth/partials/user_status_form.html",
        action=action,
        user=user,
        target_active=target_active,
    )
    action_label = gettext("Enable", request=request) if target_active else gettext("Disable", request=request)
    title = gettext("%(action)s User · %(username)s", request=request, action=action_label, username=escape(str(user.username)))
    return modal_response(title, html=modal_html)


async def user_delete_modal_response(request: Any, user: AbstractUser | None, *, action: str):
    """Confirm deleting one user; `action` takes the POST."""
    if user is None:
        return modal_not_found_response(gettext("Delete User", request=request), gettext("User not found.", request=request))
    modal_html = await render_fragment(
        request,
        "oldman/auth/partials/user_delete_form.html",
        action=action,
        user=user,
    )
    return modal_response(f"{gettext('Delete User', request=request)} · {escape(str(user.username))}", html=modal_html)


__all__ = ["user_delete_modal_response", "user_status_modal_response"]
