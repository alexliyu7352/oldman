"""
@author:alex
@date:2025/11/24
@time:07:23
"""

__author__ = "alex"

import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, Protocol, TypeVar, cast, overload

_P = ParamSpec("_P")
_R = TypeVar("_R")


class _AsyncMethodDecorator(Protocol):
    @overload
    def __call__(self, func: Callable[_P, Awaitable[_R]], /) -> Callable[_P, Awaitable[_R]]: ...

    @overload
    def __call__(self, *args: Any, **kwargs: Any) -> Callable[[Callable[_P, Awaitable[_R]]], Callable[_P, Awaitable[_R]]]: ...


def method_adaptor(decorator_factory: Callable[..., Any]) -> _AsyncMethodDecorator:
    """
    通用适配器工厂：装饰时检测函数类型，运行时零开销
    支持 @decorator 和 @decorator() 两种用法
    """

    @wraps(decorator_factory)
    def adapted_factory(*args_factory, **kwargs_factory):
        def apply_decorator_logic(func, *df_args, **df_kwargs):
            """内部助手，应用装饰器并返回正确的运行时 wrapper"""
            original_decorator = decorator_factory(*df_args, **df_kwargs)
            decorated_function = original_decorator(func)

            # 装饰时检测一次函数签名
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            # 启发式判断：第一个参数名是 'self' 或 'cls'
            is_method = params and params[0] in ("self", "cls")

            if is_method:
                # 实例方法或类方法：wrapper 直接传递参数（第一个参数会被 Python 自动绑定为 self/cls）
                @wraps(func)
                async def wrapper(*args, **kwargs):
                    # decorated_function 内部会剥离第一个参数 (self/cls)
                    # 因为我们在原装饰器内部处理了 (if view is None:)
                    return await decorated_function(*args, **kwargs)
            else:
                # 普通函数：wrapper 在调用前添加 None 占位符
                @wraps(func)
                async def wrapper(*args, **kwargs):
                    # args 此时是 (request, ...)
                    # 我们需要将它转换为 (None, request, ...)
                    # 以匹配原装饰器内部 wrapper 的期待签名 wrapper(view, request: Request, ...)
                    return await decorated_function(None, *args, **kwargs)

            return wrapper

        # --- 智能调用检测 ---

        # 检查是否是无参数调用：@add_csrf_token
        # 即：只传入了一个参数，且这个参数是可调用的（目标函数），且没有关键字参数
        if len(args_factory) == 1 and callable(args_factory[0]) and not kwargs_factory:
            func = args_factory[0]
            # 作为无参装饰器应用，调用时不传参数给 factory
            return apply_decorator_logic(func)
        else:
            # 否则，是带参数调用：@add_csrf_token() 或 @add_csrf_token(foo=bar)
            def new_decorator(func):
                # 调用时使用捕获的工厂参数
                return apply_decorator_logic(func, *args_factory, **kwargs_factory)

            return new_decorator

    return cast(_AsyncMethodDecorator, adapted_factory)
