from collections import deque
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from typing import Any, overload


class FixedSizeList(deque):
    """容量固定的 deque，满了再追加就挤掉最老的元素；即 ``deque(maxlen=size)``。

    ``in`` 逐个比较，耗时随容量线性增长。2026-09-25 实测“先判断再追加”每次约：
    容量 10 为 0.15 µs，100 为 1 µs，1000 为 10 µs，10000 为 95 µs。
    几十个以内它最快；更大的窗口又要频繁判断时，用 OptimizedFixedSizeList。
    """

    def __init__(self, size: int) -> None:
        super().__init__(maxlen=size)


class OptimizedFixedSizeList:
    """与 FixedSizeList 一样容量固定、挤掉最老的元素，但 ``in`` 不随容量变慢。

    旁边用字典记每个元素当前出现的次数：同一元素追加多次时，挤掉较早的一份后仍能查到。
    同一次实测“先判断再追加”每次约 0.3 µs，与容量无关，约 30 个元素起就比 FixedSizeList 快。
    元素必须可哈希。只提供 append、clear、in、len 与遍历。
    """

    def __init__(self, size: int) -> None:
        if not isinstance(size, int) or size <= 0:
            raise ValueError("Size must be a positive integer")
        self._items: deque[Any] = deque(maxlen=size)
        self._counts: dict[Any, int] = {}

    def append(self, item: Any) -> None:
        """追加一个元素；已满时最老的元素被挤掉。"""
        # 先算哈希：不可哈希的元素要在这里就报错。先进了队列的话，等它成为最老的元素，之后每次追加都会失败。
        hash(item)
        items = self._items
        counts = self._counts
        if len(items) == items.maxlen:
            oldest = items[0]
            remaining = counts[oldest] - 1
            if remaining:
                counts[oldest] = remaining
            else:
                del counts[oldest]
        items.append(item)
        counts[item] = counts.get(item, 0) + 1

    def clear(self) -> None:
        """清空全部元素，容量不变。"""
        self._items.clear()
        self._counts.clear()

    def __contains__(self, item: Any) -> bool:
        return item in self._counts

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Any]:
        """从最老到最新。"""
        return iter(self._items)

    def __repr__(self) -> str:
        return f"OptimizedFixedSizeList({list(self._items)})"


type Getter = Callable[[Any], Any]

_SCALAR_TYPES: tuple[type, ...] = (str, bytes, Mapping)
_TRY_CALL_ERRORS = (AttributeError, KeyError, TypeError, IndexError, ValueError, ZeroDivisionError)


def _first_result(
    funcs: Iterable[Callable[..., Any]],
    args: Iterable[Any],
    kwargs: Mapping[str, Any],
    expected_type: type | tuple[type, ...] | None,
) -> Any:
    """try_call 与 try_get 共用的循环；不带重载，两边传入的 expected_type 联合类型都能直接接受。"""
    for func in funcs:
        try:
            value = func(*args, **kwargs)
        except _TRY_CALL_ERRORS:
            continue
        if expected_type is None or isinstance(value, expected_type):
            return value
    return None


class CollectionUtils:
    """容错地读取结构不确定的数据（外部接口返回的 JSON 之类），全部是静态方法。

    改编自 yt-dlp ``yt_dlp/utils/_utils.py`` 的同名函数（Unlicense）。与原版的差别：variadic 的
    ``allowed_types`` 改名 ``scalar_types``，filter_dict 的 ``cndn`` 改名 ``predicate``；get_nested
    的键逐个传入、支持列表下标与 ``expected_type``，任何一层取不到即返回默认值。
    """

    @staticmethod
    def is_iterable_like(
        value: object,
        allowed_types: type | tuple[type, ...] = Iterable,
        blocked_types: type | tuple[type, ...] = _SCALAR_TYPES,
    ) -> bool:
        """value 是 allowed_types 的实例又不是 blocked_types 的实例；默认即“可迭代，但字符串、bytes、字典不算”。"""
        return isinstance(value, allowed_types) and not isinstance(value, blocked_types)

    @staticmethod
    def variadic(value: Any, scalar_types: type | tuple[type, ...] = _SCALAR_TYPES) -> Iterable[Any]:
        """把“一个或多个”统一成可迭代：value 本身可迭代就原样返回，否则包成 ``(value,)``。

        scalar_types 里的类型即使可迭代也当作单个值，默认是字符串、bytes 与字典。传入时整个替换默认值：
        ``variadic({"k": 1}, (str,))`` 会把字典当作可迭代原样返回。
        """
        return value if CollectionUtils.is_iterable_like(value, blocked_types=scalar_types) else (value,)

    @overload
    @staticmethod
    def try_call[T](
        *funcs: Callable[..., Any],
        expected_type: type[T],
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> T | None: ...

    @overload
    @staticmethod
    def try_call(
        *funcs: Callable[..., Any],
        expected_type: tuple[type, ...] | None = None,
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any: ...

    @staticmethod
    def try_call(
        *funcs: Callable[..., Any],
        expected_type: type | tuple[type, ...] | None = None,
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        """依次调用 funcs，返回第一个没抛常见异常、且类型与 expected_type 相符的结果；都不满足返回 None。

        吞掉的是 AttributeError、KeyError、TypeError、IndexError、ValueError、ZeroDivisionError。
        函数里写错方法名同样是 AttributeError，也只会表现为返回 None。args 可以是生成器，先读成元组，每个函数拿到同样的参数。
        """
        return _first_result(funcs, tuple(args), {} if kwargs is None else kwargs, expected_type)

    @overload
    @staticmethod
    def try_get[T](src: Any, getter: Getter | Iterable[Getter], expected_type: type[T]) -> T | None: ...

    @overload
    @staticmethod
    def try_get(src: Any, getter: Getter | Iterable[Getter], expected_type: tuple[type, ...] | None = None) -> Any: ...

    @staticmethod
    def try_get(src: Any, getter: Getter | Iterable[Getter], expected_type: type | tuple[type, ...] | None = None) -> Any:
        """用 getter（一个函数或几个备选函数）从 src 取值，规则同 try_call。

        ``CollectionUtils.try_get(data, lambda x: x["contents"]["tabs"], list) or []``
        """
        return _first_result(CollectionUtils.variadic(getter), (src,), {}, expected_type)

    @overload
    @staticmethod
    def get_nested[T](data: Any, *keys: Hashable, expected_type: type[T], default: None = None) -> T | None: ...

    @overload
    @staticmethod
    def get_nested[T, D](data: Any, *keys: Hashable, expected_type: type[T], default: D) -> T | D: ...

    @overload
    @staticmethod
    def get_nested(data: Any, *keys: Hashable, expected_type: None = None, default: Any = None) -> Any: ...

    @staticmethod
    def get_nested(data: Any, *keys: Hashable, expected_type: type | None = None, default: Any = None) -> Any:
        """沿 keys 逐层取值：映射按键取，列表、元组按整数下标取（可以为负）。

        任何一层取不到就返回 default；给了 expected_type 而取到的值类型不符，也返回 default。
        ``CollectionUtils.get_nested({"items": [{"id": 7}]}, "items", 0, "id", expected_type=int)`` 返回 7。
        """
        value = data
        for key in keys:
            if isinstance(value, Mapping):
                if key not in value:
                    return default
                value = value[key]
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and isinstance(key, int):
                if not -len(value) <= key < len(value):
                    return default
                value = value[key]
            else:
                return default
        if expected_type is not None and not isinstance(value, expected_type):
            return default
        return value

    @staticmethod
    def filter_dict[K, V](
        data: Mapping[K, V],
        predicate: Callable[[K, V], bool] = lambda _key, value: value is not None,
    ) -> dict[K, V]:
        """只保留 ``predicate(key, value)`` 为真的项；默认去掉值为 None 的项。"""
        return {key: value for key, value in data.items() if predicate(key, value)}
