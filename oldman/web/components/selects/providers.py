"""Select/Autocomplete Provider 基类。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.web.api import ApiErrorCode, DefaultApiResponse

from .choices import SelectChoice, SelectResult
from .signing import SelectContext


class SelectInvalidRequest(ValueError):
    """远程选择器请求参数非法。"""


class SelectPermissionDenied(PermissionError):
    """当前请求无权访问选择器。"""


class SelectProviderConfigError(RuntimeError):
    """Provider 配置错误。"""


class SelectProvider:
    """Select/Autocomplete provider 基类。"""

    page_size: int = 20
    max_page_size: int = 100
    db_session: AsyncSession | None = None

    async def handle_request(self, request: Any, *, context: SelectContext) -> dict[str, Any]:
        """处理请求并把 provider 级业务错误转换为统一 API payload。"""
        try:
            return await self.handle_valid_request(request, context=context)
        except SelectInvalidRequest as exc:
            return provider_api_error(ApiErrorCode.INVALID_REQUEST, str(exc), {"request": str(exc)})
        except SelectPermissionDenied as exc:
            return provider_api_error(ApiErrorCode.PERMISSION_DENIED, str(exc), {"permission": str(exc)})

    async def handle_valid_request(self, request: Any, *, context: SelectContext) -> dict[str, Any]:
        """处理搜索分页或初始值回显请求。"""
        depends = self.read_depends(request, context)
        values = self.read_initial_values(request)
        if values:
            if not await self.check_auth(request, context):
                raise SelectPermissionDenied("Select provider permission denied")
            choices = await self.get_initial(request, context, values, depends)
            return SelectResult(results=choices, more=False).to_json(label_mode=context.label_mode)

        page = read_positive_int_arg(request.args, "page", default=1)
        page_size = self.resolve_page_size(request, context)
        term = str(get_arg(request.args, "q", "") or "")
        if not await self.check_auth(request, context):
            raise SelectPermissionDenied("Select provider permission denied")

        result = await self.search(request, context, term=term, depends=depends, page=page, page_size=page_size)
        return result.to_json(label_mode=context.label_mode)

    async def check_auth(self, request: Any, context: SelectContext) -> bool:
        """检查当前请求是否允许访问 provider。"""
        return True

    async def search(
        self,
        request: Any,
        context: SelectContext,
        *,
        term: str,
        depends: dict[str, str],
        page: int,
        page_size: int,
    ) -> SelectResult:
        """执行搜索分页查询。"""
        raise NotImplementedError

    async def get_initial(self, request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]:
        """按输入顺序返回初始值可见候选。"""
        raise NotImplementedError

    def get_option(self, obj: object) -> SelectChoice:
        """把候选对象转换为 SelectChoice。"""
        raise NotImplementedError

    def read_depends(self, request: Any, context: SelectContext) -> dict[str, str]:
        """读取并校验白名单依赖字段。"""
        depends: dict[str, str] = {}
        for key, value in iter_args(getattr(request, "args", {})):
            if not key.startswith("depends[") or not key.endswith("]"):
                continue
            name = key.removeprefix("depends[").removesuffix("]")
            if name not in context.dependent_fields:
                raise SelectInvalidRequest(f"Unexpected dependent field: {name}")
            if value in {"", None}:
                continue
            depends[name] = str(value)
        return depends

    def read_initial_values(self, request: Any) -> list[str]:
        """读取单选 value 或多选 values 初始值。"""
        values = getlist_arg(request.args, "values")
        if values:
            return [str(value) for value in values if str(value) != ""]
        value = get_arg(request.args, "value", "")
        return [str(value)] if value not in {"", None} else []

    def resolve_page_size(self, request: Any, context: SelectContext) -> int:
        """解析分页大小并应用 provider 与签名上下文上限。"""
        maximum = min(self.max_page_size, self.page_size, context.page_size)
        return read_positive_int_arg(request.args, "page_size", default=maximum, maximum=maximum)


class DataSelectProvider(SelectProvider):
    """结构化数据 Select/Autocomplete provider。"""

    async def get_choices(self, request: Any, context: SelectContext) -> Sequence[object]:
        """返回结构化候选数据。"""
        return []

    async def search(
        self,
        request: Any,
        context: SelectContext,
        *,
        term: str,
        depends: dict[str, str],
        page: int,
        page_size: int,
    ) -> SelectResult:
        """在 Python 层完成结构化数据搜索和分页。"""
        choices = await self.filter_queryset(request, context, await self.get_choices(request, context), term, depends)
        start = (page - 1) * page_size
        window = list(choices)[start : start + page_size + 1]
        return SelectResult(results=[self.get_option(item) for item in window[:page_size]], more=len(window) > page_size)

    async def filter_queryset(
        self,
        request: Any,
        context: SelectContext,
        choices: Sequence[object],
        term: str,
        depends: dict[str, str],
    ) -> Sequence[object]:
        """按文本标签执行默认大小写不敏感搜索。"""
        if not term.strip():
            return choices
        normalized = term.strip().lower()
        return [choice for choice in choices if normalized in self.get_option(choice).text.lower()]

    async def get_initial(self, request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]:
        """按输入 values 顺序回显当前可见候选。"""
        options = [self.get_option(item) for item in await self.get_choices(request, context)]
        by_id = {str(option.id): option for option in options}
        return [by_id[value] for value in values if value in by_id]

    def get_option(self, obj: object) -> SelectChoice:
        """默认支持 (value, label)、dict 和普通对象。"""
        if isinstance(obj, SelectChoice):
            return obj
        if isinstance(obj, tuple):
            if len(obj) != 2:
                raise SelectProviderConfigError("Tuple choices must be (value, label)")
            return SelectChoice(id=obj[0], text=str(obj[1]))
        if isinstance(obj, dict):
            return SelectChoice(id=obj.get("id", obj.get("value")), text=str(obj.get("text", obj.get("label", ""))))
        value = getattr(obj, "id", getattr(obj, "value", None))
        label = getattr(obj, "text", getattr(obj, "label", value))
        return SelectChoice(id=value, text=str(label))


class ModelSelectProvider(SelectProvider):
    """SQLAlchemy Select/Autocomplete provider 基类。"""

    # 多数据库业务通过子类覆盖该属性；默认对象仍由 DB 模块惰性初始化。
    database_manager: DatabaseManager = default_db_manager
    model: type[Any] | None = None
    search_fields: tuple[str, ...] | list[str] = ()
    label_field: str = "name"
    value_field: str = "id"

    async def handle_request(self, request: Any, *, context: SelectContext) -> dict[str, Any]:
        """在同一个只读 session 内处理数据库型 provider 请求。"""
        async with self.database_manager.get_read_session() as session:
            self.db_session = session
            try:
                return await super().handle_request(request, context=context)
            finally:
                self.db_session = None

    async def get_queryset(self, request: Any, context: SelectContext):
        """返回基础 SQLAlchemy 查询。"""
        raise NotImplementedError("ModelSelectProvider.get_queryset() must be implemented")

    async def search(
        self,
        request: Any,
        context: SelectContext,
        *,
        term: str,
        depends: dict[str, str],
        page: int,
        page_size: int,
    ) -> SelectResult:
        """执行数据库搜索分页查询。"""
        query = await self.get_queryset(request, context)
        query = await self.filter_queryset(request, context, query, term, depends)
        session = self.require_db_session()
        result = await session.execute(query.limit(page_size + 1).offset((page - 1) * page_size))
        rows = list(result.scalars().all())
        return SelectResult(results=[self.get_option(row) for row in rows[:page_size]], more=len(rows) > page_size)

    async def filter_queryset(self, request: Any, context: SelectContext, query: Any, term: str, depends: dict[str, str]):
        """按 search_fields 生成默认 SQL LIKE 搜索。"""
        if not term.strip() or not self.search_fields:
            return query
        like = f"%{term.strip()}%"
        if self.model is None:
            raise SelectProviderConfigError("ModelSelectProvider.model must be set")
        expressions = [getattr(self.model, field).like(like) for field in self.search_fields]
        return query.where(or_(*expressions))

    async def get_initial(self, request: Any, context: SelectContext, values: list[str], depends: dict[str, str]) -> list[SelectChoice]:
        """按输入顺序读取初始值候选。"""
        query = await self.get_queryset(request, context)
        if self.model is None:
            raise SelectProviderConfigError("ModelSelectProvider.model must be set")
        value_column = getattr(self.model, self.value_field)
        result = await self.require_db_session().execute(query.where(value_column.in_(values)))
        options = [self.get_option(row) for row in result.scalars().all()]
        by_id = {str(option.id): option for option in options}
        return [by_id[value] for value in values if value in by_id]

    def get_option(self, obj: object) -> SelectChoice:
        """把 SQLAlchemy model 实例转换为 SelectChoice。"""
        return SelectChoice(id=getattr(obj, self.value_field), text=str(getattr(obj, self.label_field)))

    def require_db_session(self) -> AsyncSession:
        """Return the request-scoped SQLAlchemy session."""
        if self.db_session is None:
            raise RuntimeError("ModelSelectProvider requires an active database session")
        return self.db_session


def provider_api_error(error_code: ApiErrorCode, message: str, errors: dict[str, object]) -> dict[str, Any]:
    """构造 provider 级统一错误 payload。"""
    return DefaultApiResponse(error_code=error_code, message=message, data={"errors": errors}).to_dict()


def get_arg(args: object, key: str, default: object = None) -> object:
    """从 request.args 读取单值参数。"""
    getter = getattr(args, "get", None)
    return default if getter is None else first_arg_value(getter(key, default))


def getlist_arg(args: object, key: str) -> list[object]:
    """从 request.args 读取多值参数。"""
    getlist = getattr(args, "getlist", None)
    if getlist is not None:
        return list(getlist(key))
    value = get_arg(args, key, [])
    if value in {"", None}:
        return []
    return value if isinstance(value, list) else [value]


def iter_args(args: object) -> list[tuple[str, object]]:
    """遍历 request.args 的单值参数。"""
    if hasattr(args, "items"):
        return [(key, first_arg_value(value)) for key, value in cast(Any, args).items()]
    return []


def first_arg_value(value: object) -> object:
    """把 Sanic 多值查询参数规范为首个值。"""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def read_positive_int_arg(args: object, key: str, *, default: int, maximum: int | None = None) -> int:
    """读取正整数请求参数，非法值或超过上限时抛出请求错误。"""
    value = get_arg(args, key, None)
    if value in {"", None}:
        return default
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        raise SelectInvalidRequest(f"Invalid integer parameter: {key}") from None
    if number < 1:
        raise SelectInvalidRequest(f"Invalid positive integer parameter: {key}")
    if maximum is not None and number > maximum:
        raise SelectInvalidRequest(f"Parameter exceeds maximum: {key}")
    return number
