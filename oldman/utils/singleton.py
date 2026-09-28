"""
@author:alex
@date:2024/9/15
@time:上午3:28
"""

__author__ = "alex"
import threading
from types import new_class
from typing import Any, ClassVar, TypeVar, cast

T = TypeVar("T")  # 被装饰类实例的类型


class SingletonMeta(type):
    """让类在进程内只创建一个实例：第一次调用时创建，之后的调用都返回它，**再传的参数被忽略**。

    每个类各自一个实例（子类与父类互不共用），各自一把锁：一个单例的 __init__ 里再创建另一个单例不会死锁。
    实例已存在时只查一次字典、不碰锁（约 95 ns，原先先查锁再查实例约 160 ns）。
    异质容器用宽类型、接口返回 T，是这类“类→实例缓存”在静态类型里的常见折中。
    """

    _instances: ClassVar[dict[type[Any], Any]] = {}
    _locks: ClassVar[dict[type[Any], threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __call__(cls: type[T], *args: Any, **kwargs: Any) -> T:
        # 快速路径：直接下标取值（缺失只在第一次创建时发生）；取出的是 Any，不必 typing.cast——它在运行时是一次函数调用
        try:
            return SingletonMeta._instances[cls]
        except KeyError:
            pass

        lock = SingletonMeta._locks.get(cls)
        if lock is None:
            with SingletonMeta._locks_guard:
                lock = SingletonMeta._locks.setdefault(cls, threading.Lock())
        with lock:
            instance = SingletonMeta._instances.get(cls)
            if instance is None:
                instance = super(SingletonMeta, cast(SingletonMeta, cls)).__call__(*args, **kwargs)
                SingletonMeta._instances[cls] = instance
        return instance


_combined_metaclasses: dict[type, type] = {}
_combined_guard = threading.Lock()


def _singleton_metaclass(metaclass: type) -> type:
    """SingletonMeta 与类原有的元类（ABCMeta、pydantic 的元类等）组合成一个，避免“元类冲突”。"""
    if issubclass(metaclass, SingletonMeta):
        return metaclass
    if metaclass is type:
        return SingletonMeta
    with _combined_guard:
        combined = _combined_metaclasses.get(metaclass)
        if combined is None:
            combined = _combined_metaclasses[metaclass] = new_class(f"Singleton{metaclass.__name__}", (SingletonMeta, metaclass))
    return combined


def singleton(cls: type[T]) -> type[T]:  # noqa: UP047 -- the explicit generic signature is part of the public API
    """类装饰器：让这个类在进程内只有一个实例，规则见 SingletonMeta。

    装饰后仍然是类（原类的子类）：isinstance、issubclass、继承照常；再派生的子类各自也是单例。
    类原本带自定义元类（如 ABC、pydantic 模型）时，自动与 SingletonMeta 组合。``__wrapped__`` 是原类，
    测试里用它创建不受单例约束的独立实例。
    """

    def body(namespace: dict[str, Any]) -> None:
        namespace["__wrapped__"] = cls
        namespace["__module__"] = cls.__module__
        namespace["__qualname__"] = cls.__qualname__
        namespace["__doc__"] = cls.__doc__

    wrapper = new_class(cls.__name__, (cls,), {"metaclass": _singleton_metaclass(type(cls))}, body)
    return cast(type[T], wrapper)


_shared_containers: dict[tuple[type, str], Any] = {}
_shared_guard = threading.Lock()


def _shared_container(kind: type, name: str) -> Any:
    try:
        return _shared_containers[(kind, name)]
    except KeyError:
        pass
    with _shared_guard:
        return _shared_containers.setdefault((kind, name), kind())


def shared_dict(name: str) -> dict[Any, Any]:
    """按名字取进程内共享的 dict：同一个名字在任何模块里拿到的都是同一个对象，不同名字互不相干。

    给“两个模块要共用一个容器，却不能互相 import 定义它的模块（会循环引用）”的场景用：双方只需约定名字。
    名字写错会悄悄得到另一个容器，所以把它定义成常量，放在不会引起循环引用的地方。
    返回的就是普通 dict；第一次取时创建，多线程同时第一次取也只创建一个。
    """
    return _shared_container(dict, name)


def shared_list(name: str) -> list[Any]:
    """按名字取进程内共享的 list，规则同 shared_dict；dict 与 list 用同一个名字互不相干。"""
    return _shared_container(list, name)
