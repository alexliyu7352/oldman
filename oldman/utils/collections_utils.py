import collections
import dataclasses
import os
from collections import deque
from typing import Any, Protocol, Self, TypeVar, runtime_checkable

import aiofiles
import ujson as json


@runtime_checkable
class DataclassProtocol(Protocol):
    """用于类型提示的 dataclass 协议"""

    __dataclass_fields__: dict[str, Any]


# 定义一个协议来描述可序列化的dataclass
@runtime_checkable
class SerializableProtocol(DataclassProtocol, Protocol):
    """描述可序列化的dataclass类型的协议"""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any: ...

    @classmethod
    def from_json(cls, json_str: str) -> Any: ...


T = TypeVar("T", bound="SerializableMixin")


class FixedSizeList(deque):
    def __init__(self, size: int) -> None:
        super().__init__(maxlen=size)


class OptimizedFixedSizeList:
    """
    一个固定大小的列表，内部使用 deque 和 set 来实现
    O(1) 时间复杂度的 append 和成员资格测试。
    不一定更快, 至少测试情况是这样的
    """

    def __init__(self, size: int) -> None:
        if not isinstance(size, int) or size <= 0:
            raise ValueError("Size must be a positive integer")
        self._deque = deque(maxlen=size)
        self._set = set()

    def append(self, item: Any) -> None:
        """添加一个新元素。如果队列已满，最老的元素将被丢弃。"""
        # 检查队列是否已满
        if len(self._deque) == self._deque.maxlen:
            # 在添加新元素之前，从 set 中移除将被 deque 挤出的最老的元素
            old_item = self._deque[0]
            if old_item in self._set:
                self._set.remove(old_item)

        # 添加新元素
        self._deque.append(item)
        self._set.add(item)

    def __contains__(self, item: Any) -> bool:
        """使用 set 实现 O(1) 复杂度的快速成员资格测试"""
        return item in self._set

    def __len__(self) -> int:
        return len(self._deque)

    def __iter__(self):
        """返回 deque 的迭代器"""
        return iter(self._deque)

    def __repr__(self) -> str:
        return f"FixedSizeList({list(self._deque)})"


class SerializableMixin:
    """
    可序列化数据类的 Mixin，支持JSON序列化、反序列化、保存到文件和从文件加载
    """

    def to_dict(self) -> dict[str, Any]:
        """将dataclass实例转换为字典"""
        return dataclasses.asdict(self)  # type: ignore

    def to_json(self) -> str:
        """将dataclass实例序列化为JSON字符串"""

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """从字典创建dataclass实例"""
        field_names = {f.name for f in dataclasses.fields(cls)}  # type: ignore
        filtered_data = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered_data)

    @classmethod
    def from_json(cls, json_str: str) -> Self:
        """从JSON字符串创建dataclass实例"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def save_to_file(self, file_path: str) -> bool:
        """
        同步保存dataclass实例到JSON文件

        Args:
            file_path: 保存的文件路径

        Returns:
            bool: 保存是否成功
        """
        try:
            dirname = os.path.dirname(file_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.to_json())
            return True
        except Exception as e:
            print(f"保存到文件失败: {e}")
            return False

    async def save_to_file_async(self, file_path: str) -> bool:
        """
        异步保存dataclass实例到JSON文件

        Args:
            file_path: 保存的文件路径

        Returns:
            bool: 保存是否成功
        """
        try:
            dirname = os.path.dirname(file_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)

            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(self.to_json())
            return True
        except Exception as e:
            print(f"异步保存到文件失败: {e}")
            return False

    @classmethod
    def load_from_file(cls, file_path: str) -> Self:
        """
        同步从JSON文件加载dataclass实例

        Args:
            file_path: JSON文件路径

        Returns:
            Self: 加载的dataclass实例，如果加载失败则返回默认实例
        """
        try:
            if not os.path.exists(file_path):
                return cls()
            with open(file_path, encoding="utf-8") as f:
                json_data = f.read()
            return cls.from_json(json_data)
        except Exception:
            return cls()

    @classmethod
    async def load_from_file_async(cls, file_path: str) -> Self:
        """
        异步从JSON文件加载dataclass实例

        Args:
            file_path: JSON文件路径

        Returns:
            Self: 加载的dataclass实例，如果加载失败则返回默认实例
        """
        try:
            if not os.path.exists(file_path):
                return cls()
            async with aiofiles.open(file_path, encoding="utf-8") as f:
                json_data = await f.read()
            return cls.from_json(json_data)
        except Exception:
            return cls()


def get_nested(data, keys, default=None):
    """安全地从嵌套字典中获取值"""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, default)
        else:
            return default
    return data


class NO_DEFAULT:
    pass


def is_iterable_like(x, allowed_types=collections.abc.Iterable, blocked_types=NO_DEFAULT):  # pyright: ignore[reportAttributeAccessIssue] -- available at runtime
    if blocked_types is NO_DEFAULT:
        blocked_types = (str, bytes, collections.abc.Mapping)  # pyright: ignore[reportAttributeAccessIssue] -- available at runtime
    return isinstance(x, allowed_types) and not isinstance(x, blocked_types)


def variadic(x, allowed_types=NO_DEFAULT):
    if not isinstance(allowed_types, tuple | type):
        allowed_types = tuple(allowed_types)
    return x if is_iterable_like(x, blocked_types=allowed_types) else (x,)  # pyright: ignore[reportArgumentType] -- runtime accepts type tuples


def try_call(*funcs, expected_type=None, args=[], kwargs={}):  # noqa: B006 -- the mutable defaults are part of the public signature and are never mutated
    for f in funcs:
        try:
            val = f(*args, **kwargs)
        except (AttributeError, KeyError, TypeError, IndexError, ValueError, ZeroDivisionError):
            pass
        else:
            if expected_type is None or isinstance(val, expected_type):
                return val


def try_get(src, getter, expected_type=None):
    return try_call(*variadic(getter), args=(src,), expected_type=expected_type)


def filter_dict(dct, cndn=lambda _, v: v is not None):
    return {k: v for k, v in dct.items() if cndn(k, v)}
