"""
@author:alex
@date:2024/9/15
@time:上午3:28
"""

__author__ = "alex"
import threading
import warnings
from collections.abc import Callable
from types import new_class
from typing import Any, ClassVar, Generic, ParamSpec, TypeVar, cast

T = TypeVar("T")  # 被装饰类实例的类型
P = ParamSpec("P")  # 被装饰类 __init__ / __call__ 的参数签名


class SingletonCallable(Generic[T, P]):  # noqa: UP046 -- the explicit generic signature is part of the public API
    """类以外的可调用”（工厂函数）"""

    def __init__(self, cls: Callable[P, T]) -> None:
        self._cls = cls
        self._instance: T | None = None
        self._lock = threading.Lock()

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self._cls(*args, **kwargs)
        elif args or kwargs:
            # 警告：单例已存在，忽略新参数
            warnings.warn("Singleton instance already exists, ignoring new arguments", UserWarning, stacklevel=2)
        return self._instance


class Singleton(Generic[T, P]):  # noqa: UP046 -- the explicit generic signature is part of the public API
    """装饰后名字绑定到可调用实例，严格意义上不再是类；某些需要类对象的场景（注册、issubclass、ABC 钩子等）会不兼容。"""

    def __init__(self, cls: type[T]) -> None:
        self.__wrapped__: type[T] = cls  # 便于 inspect / IDE
        self._instance: T | None = None
        self._lock = threading.Lock()  # 每个单例独立的锁

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self.__wrapped__(*args, **kwargs)
        return self._instance


class SingletonMeta(type):
    """
    因为装饰器返回了“带单例元类”的子类，后续再派生的子类也会继续是单例
    如果原类本身已有自定义元类（如 ABCMeta），SingletonMeta 可能产生元类冲突
    异质容器用宽类型，接口返回用 T。这是这类“type→instance 缓存”在静态类型系统里的常见折中
    """

    _instances: ClassVar[dict[type[Any], Any]] = {}
    _locks: ClassVar[dict[type[Any], threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __call__(cls: type[T], *args: Any, **kwargs: Any) -> T:
        # 拿/建该类的专属锁（用 guard 串行化“建锁”过程）
        lock = SingletonMeta._locks.get(cls)
        if lock is None:
            with SingletonMeta._locks_guard:
                lock = SingletonMeta._locks.setdefault(cls, threading.Lock())

        inst = SingletonMeta._instances.get(cls)
        if inst is None:
            # 第二重检查在类专属锁内完成
            assert lock is not None
            with lock:
                inst = SingletonMeta._instances.get(cls)
                if inst is None:
                    # 用父元类的实现，避免 super(...) + cast
                    # 不必要的强制转换，可能掩盖类型问题
                    inst = super(SingletonMeta, cast(SingletonMeta, cls)).__call__(*args, **kwargs)
                    SingletonMeta._instances[cls] = inst

        return cast(T, inst)


def singleton_adv(cls: type[T]) -> type[T]:  # noqa: UP047 -- the explicit generic signature is part of the public API
    class SingletonWrapper(cls, metaclass=SingletonMeta):  # type: ignore
        __wrapped__ = cls  # 便于 inspect / tooling

    # 可选：保留原来的元信息，调试更友好
    SingletonWrapper.__name__ = cls.__name__
    SingletonWrapper.__qualname__ = cls.__qualname__
    SingletonWrapper.__module__ = cls.__module__
    SingletonWrapper.__doc__ = cls.__doc__

    return cast(type[T], SingletonWrapper)


class SingletonContainer:
    # 不同类 -> 各自的实例（异质容器）
    _instances: ClassVar[dict[type[Any], Any]] = {}
    # 不同类 -> 各自的锁
    _locks: ClassVar[dict[type[Any], threading.Lock]] = {}
    # 仅用于“创建专属锁”这一步的串行化
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def get_instance(cls, container_class: type[T], *args: Any, **kwargs: Any) -> T:
        # 取/建该类的专属锁
        lock = cls._locks.get(container_class)
        if lock is None:
            with cls._locks_guard:
                lock = cls._locks.setdefault(container_class, threading.Lock())

        # DCL：锁外快速路径，锁内二次检查
        inst = cls._instances.get(container_class)
        if inst is None:
            assert lock is not None
            with lock:
                inst = cls._instances.get(container_class)
                if inst is None:
                    inst = container_class(*args, **kwargs)
                    cls._instances[container_class] = inst

        return cast(T, inst)


def singleton_container(container_class: type[T]) -> type[T]:  # noqa: UP047 -- the explicit generic signature is part of the public API
    """把类包装成通过 SingletonContainer 管理实例的类。"""

    def body(ns: dict[str, Any]) -> None:
        # 关键：给 cls 加类型标注
        def __new__(cls: type[Any], *args: Any, **kwargs: Any) -> Any:
            return SingletonContainer.get_instance(container_class, *args, **kwargs)

        ns["__new__"] = __new__
        ns["__wrapped__"] = container_class
        ns["__doc__"] = container_class.__doc__

    Wrapper = new_class(
        container_class.__name__,
        (container_class,),
        {},  # 这里不需要自定义元类
        body,
    )
    Wrapper.__module__ = container_class.__module__
    Wrapper.__qualname__ = container_class.__qualname__

    return cast(type[T], Wrapper)


# 使用示例
@singleton_container
class SingletonDict(dict):
    pass


@singleton_container
class SingletonList(list):
    pass
