"""
@author:alex
@date:2025/11/24
@time:00:52
"""

__author__ = "alex"

from jinja2 import nodes
from jinja2.ext import Extension
from markupsafe import Markup


class CsrfExtension(Extension):
    """
    Jinja2 CSRF Token Extension

    从模板 context 中读取 request 对象（sanic-ext 自动注入）

    Usage:
        <form method="post">
            {% csrf_token %}
        </form>
    """

    tags = {"csrf_token"}

    def parse(self, parser):
        """
        解析 {% csrf_token %} 标签

        关键点：
        1. sanic-ext 的 render 函数已经将 request 注入到 context
        2. 使用 nodes.Name('request', 'load') 访问 context['request']
        3. 通过 nodes.Getattr 获取 request.ctx.csrf_token
        """
        lineno = next(parser.stream).lineno

        # 从 context 中获取 request 对象
        # 等价于: request = context['request']
        request_node = nodes.Name("request", "load", lineno=lineno)

        # 获取 request.ctx
        # 等价于: request.ctx
        ctx_node = nodes.Getattr(request_node, "ctx", "load", lineno=lineno)

        # 获取 request.ctx.csrf_token
        # 等价于: request.ctx.csrf_token
        csrf_token_node = nodes.Getattr(ctx_node, "csrf_token", "load", lineno=lineno)

        # 调用 _render 方法，传入 csrf_token
        call = self.call_method("_render", [csrf_token_node], lineno=lineno)

        return nodes.Output([call], lineno=lineno)

    def _render(self, csrf_token):
        """渲染 CSRF token 隐藏字段"""
        if csrf_token:
            html = f'<input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">'
            return Markup(html)
        return Markup("")
