"""Select/Autocomplete 中心 provider endpoint 辅助。"""

from __future__ import annotations

from typing import Any

from oldman.web.api import ApiErrorCode, DefaultApiResponse
from oldman.web.http import OldmanHTTPMethodView
from oldman.web.response import json_response

from .providers import get_arg
from .registry import SelectRegistry, select_registry
from .signing import SelectBindError, verify_select_context


async def select_provider_payload(
    request: Any,
    provider_name: str,
    *,
    registry: SelectRegistry = select_registry,
    secret_key: str,
) -> tuple[dict[str, Any], int]:
    """验证 bind 并分发 provider，返回 JSON payload 和 HTTP status。"""
    provider_cls = registry.get(provider_name)
    if provider_cls is None:
        return api_error(ApiErrorCode.NOT_FOUND, "Select provider not found", {"provider": "Select provider not found"}, {"provider": provider_name}), 404

    try:
        context = verify_select_context(str(get_arg(request.args, "bind", "") or ""), secret_key=secret_key)
    except SelectBindError:
        return api_error(ApiErrorCode.INVALID_REQUEST, "Invalid select binding", {"bind": "Invalid select binding"}, {"provider": provider_name}), 400

    if context.provider != provider_name:
        return api_error(ApiErrorCode.INVALID_REQUEST, "Invalid select provider", {"provider": "Invalid select provider"}, {"provider": provider_name}), 400

    provider = provider_cls()
    payload = await provider.handle_request(request, context=context)
    return payload, status_for_provider_payload(payload)


class SelectProviderView(OldmanHTTPMethodView):
    """Select/Autocomplete 中心 provider endpoint。"""

    require_authenticated = True
    require_staff = True
    response_mode = "json"

    def __init__(self, *, registry: SelectRegistry = select_registry, secret_key: str) -> None:
        """保存 provider registry 和签名密钥。"""
        self.registry = registry
        self.secret_key = secret_key

    async def get(self, request: Any, provider_name: str):
        """验证 bind 并分发 provider。"""
        payload, status = await select_provider_payload(
            request,
            provider_name,
            registry=self.registry,
            secret_key=self.secret_key,
        )
        return json_response(payload, status=status)


def api_error(error_code: ApiErrorCode, message: str, errors: dict[str, object], data: dict[str, object]) -> dict[str, Any]:
    """通过 DefaultApiResponse 构造非表单组件错误 payload。"""
    return DefaultApiResponse(error_code=error_code, message=message, data={**data, "errors": errors}).to_dict()


def status_for_provider_payload(payload: dict[str, Any]) -> int:
    """按 provider 返回的统一错误码确定 HTTP status。"""
    error_code = payload.get("error_code", ApiErrorCode.OK)
    if error_code == ApiErrorCode.PERMISSION_DENIED:
        return 403
    if error_code == ApiErrorCode.INVALID_REQUEST:
        return 400
    return 200
