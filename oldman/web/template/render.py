"""多语言模板渲染工具"""

from typing import Any

from jinja2 import Environment

from oldman.web.response import Response
from oldman.web.routing import WebApp
from oldman.web.template import render_template


async def i18n_render(
    template_name: str = "",
    status: int = 200,
    headers: dict[str, str] | None = None,
    content_type: str = "text/html; charset=utf-8",
    app: WebApp | None = None,
    environment: Environment | None = None,
    context: dict[str, Any] | None = None,
    *,
    template_source: str = "",
) -> Response:
    if not context:
        context = {}
    # request = Request.get_current()
    # context.setdefault("url_for", request.ctx.url_for)
    # context.setdefault("get_alternate_urls", request.ctx.get_alternate_urls)
    # context.setdefault("locale", request.ctx.locale)
    return await render_template(
        template_name=template_name,
        status=status,
        headers=headers,
        content_type=content_type,
        app=app,
        environment=environment,
        context=context,
        template_source=template_source,
    )
