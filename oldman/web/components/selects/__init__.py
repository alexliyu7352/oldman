"""Oldman 后端 Select/Autocomplete 组件入口。"""

from .choices import SelectChoice, SelectResult
from .providers import DataSelectProvider, ModelSelectProvider, SelectProvider, SelectProviderConfigError
from .registry import SelectRegistry, select_registry
from .signing import SelectBindError, SelectContext, sign_select_context, verify_select_context
from .views import SelectProviderView

__all__ = [
    "DataSelectProvider",
    "ModelSelectProvider",
    "SelectBindError",
    "SelectChoice",
    "SelectContext",
    "SelectProvider",
    "SelectProviderConfigError",
    "SelectProviderView",
    "SelectRegistry",
    "SelectResult",
    "select_registry",
    "sign_select_context",
    "verify_select_context",
]
