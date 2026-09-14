"""Tailwind/Oldman 表单主题类。"""

from __future__ import annotations

from .base import OldmanForm, TableFilterForm
from .models import OldmanModelForm
from .renderers import TailwindFieldRenderer, TailwindFormRenderer


class TailwindForm(OldmanForm):
    """业务默认 Tailwind 普通表单基类。"""

    renderer_class = TailwindFormRenderer
    field_renderer_class = TailwindFieldRenderer


class TailwindTableFilterForm(TableFilterForm):
    """业务默认 Tailwind 表格筛选表单基类。"""

    renderer_class = TailwindFormRenderer
    field_renderer_class = TailwindFieldRenderer


class TailwindModelForm(OldmanModelForm):
    """业务默认 Tailwind 模型表单基类。"""

    renderer_class = TailwindFormRenderer
    field_renderer_class = TailwindFieldRenderer


__all__ = ["TailwindForm", "TailwindModelForm", "TailwindTableFilterForm"]
