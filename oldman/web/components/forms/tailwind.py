"""Tailwind/Oldman 表单主题类。"""

from __future__ import annotations

from .base import Form, TableFilterForm
from .models import ModelForm
from .renderers import TailwindFieldRenderer, TailwindFormRenderer


class TailwindForm(Form):
    """业务默认 Tailwind 普通表单基类。"""

    renderer_class = TailwindFormRenderer
    field_renderer_class = TailwindFieldRenderer


class TailwindTableFilterForm(TableFilterForm):
    """业务默认 Tailwind 表格筛选表单基类。"""

    renderer_class = TailwindFormRenderer
    field_renderer_class = TailwindFieldRenderer


class TailwindModelForm(ModelForm):
    """业务默认 Tailwind 模型表单基类。"""

    renderer_class = TailwindFormRenderer
    field_renderer_class = TailwindFieldRenderer


__all__ = ["TailwindForm", "TailwindModelForm", "TailwindTableFilterForm"]
