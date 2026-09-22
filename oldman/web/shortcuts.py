"""读取一个对象或者返回 404 的快捷函数。"""

from __future__ import annotations

from typing import Any

from oldman.web.exceptions import NotFound


async def get_object_or_404[TModel](session: Any, model: type[TModel], object_id: Any, *, message: str | None = None) -> TModel:
    """在调用方的事务里按主键读一个对象，读不到就抛 `NotFound`。

    URL 里的主键来自浏览器，不存在是正常情况，应该走 404 页面/JSON，而不是让 `None` 继续流到模板或
    表单里变成 500。默认信息是 "<模型类名> <主键> was not found"，需要给用户看别的话时传 `message`。
    错误的主键格式（多一段、类型不对）由路由的类型约束和 `session.get` 自己报。
    """
    instance = await session.get(model, object_id)
    if instance is None:
        raise NotFound(message or f"{getattr(model, '__name__', model)} {object_id} was not found")
    return instance


__all__ = ["get_object_or_404"]
