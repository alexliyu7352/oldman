"""Jinja tags for language alternates and a language switcher."""

from __future__ import annotations

from typing import Any

from jinja2 import TemplateNotFound, nodes
from jinja2.ext import Extension
from markupsafe import Markup, escape

from oldman.web.i18n.assets import direct_flag_url
from oldman.web.request import Request


class I18nExtension(Extension):
    """Render language-aware URL metadata through the configured Web service."""

    tags = {"alternate_urls", "lang_switcher"}

    def parse(self, parser: Any) -> nodes.Node:
        """Parse an alternate-URL or language-switcher tag."""
        tag_token = next(parser.stream)
        lineno = tag_token.lineno
        request_node = nodes.Name("request", "load", lineno=lineno)

        if tag_token.value == "alternate_urls":
            call = self.call_method(
                "_render_alternate_urls",
                [request_node],
                lineno=lineno,
            )
            return nodes.CallBlock(call, [], [], [], lineno=lineno)

        template_argument = parser.parse_expression() if parser.stream.current.test("string") else nodes.Const(None)
        call = self.call_method(
            "_render_lang_switcher",
            [request_node, template_argument],
            lineno=lineno,
        )
        return nodes.CallBlock(call, [], [], [], lineno=lineno)

    @staticmethod
    def _service() -> Any:
        """Resolve the singleton lazily to avoid a template/service import cycle."""
        from oldman.web.i18n.translation import translation

        return translation

    async def _get_host(self, request: Request) -> str:
        """Return the configured public domain or the current request origin."""
        service = self._service()
        if service.public_domain:
            return str(service.public_domain)
        return f"{request.scheme}://{request.host}".rstrip("/")

    async def _render_alternate_urls(
        self,
        request: Request,
        caller: Any = None,
    ) -> Markup:
        """Render escaped SEO alternate links for every configured language."""
        del caller
        service = self._service()
        if not service.use_i18n_path:
            return Markup("")

        query_string = str(request.query_string or "")
        full_path = f"{request.path}?{query_string}" if query_string else request.path
        domain = await self._get_host(request)
        links: list[Markup] = []

        for definition in service.definitions:
            path = full_path if definition.code == service.default_language else f"/{definition.code}{full_path}"
            links.append(
                Markup('<link rel="alternate" hreflang="{}" href="{}">').format(
                    escape(definition.code),
                    escape(f"{domain}{path}"),
                )
            )

        links.append(Markup('<link rel="alternate" hreflang="x-default" href="{}">').format(escape(f"{domain}{full_path}")))
        return Markup("\n").join(links)

    async def _render_lang_switcher(
        self,
        request: Request,
        custom_template: str | None = None,
        caller: Any = None,
    ) -> Markup:
        """Render the configured template or a small escaped fallback switcher."""
        del caller
        service = self._service()
        if not service.use_i18n_path:
            return Markup("")

        current_language = service.resolve_language(str(getattr(request.ctx, "locale", "") or "")) or service.default_language
        query_string = str(request.query_string or "")
        full_path = f"{request.path}?{query_string}" if query_string else request.path
        language_data: list[dict[str, Any]] = []

        for definition in service.definitions:
            path = full_path if definition.code == service.default_language else f"/{definition.code}{full_path}"
            language_data.append(
                {
                    "code": definition.code,
                    "name": definition.name,
                    "flag": definition.flag,
                    "flagUrl": direct_flag_url(
                        definition.flag,
                        static_url=service.static_url,
                    ),
                    "url": path,
                    "is_current": definition.code == current_language,
                }
            )

        template_name = custom_template or "i18n/lang_switcher.html"
        try:
            template = self.environment.get_template(template_name)
        except TemplateNotFound:
            return self._render_fallback_switcher(language_data)
        return Markup(
            await template.render_async(
                current_locale=current_language,
                languages=language_data,
            )
        )

    @staticmethod
    def _render_fallback_switcher(
        language_data: list[dict[str, Any]],
    ) -> Markup:
        """Render an escaped minimal switcher when no project template exists."""
        links: list[Markup] = []
        for language in language_data:
            if language["is_current"]:
                links.append(Markup('<span class="lang-current">{}</span>').format(escape(language["name"])))
            else:
                links.append(
                    Markup('<a href="{}" class="lang-link" hreflang="{}">{}</a>').format(
                        escape(language["url"]),
                        escape(language["code"]),
                        escape(language["name"]),
                    )
                )
        return Markup(" | ").join(links)


__all__ = ["I18nExtension"]
