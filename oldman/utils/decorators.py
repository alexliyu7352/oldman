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
    让一个装饰器同时用于普通视图函数和类视图方法。

    **只适配一种内层签名**:decorator_factory 返回的装饰器,包出来的函数必须是
    `wrapper(view, request, *args, **kwargs)`,并且 view 为 None 时按普通函数调用。
    框架的认证、CSRF、指纹装饰器都是这个形状;别的形状用它会把参数错位。

    函数还是方法,在**装饰时**按第一个参数的名字判断:叫 `self` 或 `cls` 就是方法,
    否则当普通函数,调用时在最前面补一个 None 作 view。方法的第一个参数若不叫
    self/cls,会走错分支。

    每次调用多一层 `async def` 包装和一次 await,不是零开销。

    支持 @decorator 和 @decorator(...) 两种用法:只传了一个可调用对象、没有关键字参数时
    视为无参用法。因此工厂的唯一参数本身是可调用对象时(例如一个回调),必须用关键字传。
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
