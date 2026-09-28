from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Self

import msgspec
import orjson
from pydantic import BaseModel

from oldman.utils.files import atomic_write


class MsgspecModel(msgspec.Struct):
    # 模块/类级复用的编码器（默认配置够用；需要可在 __init_subclass__ 里改）
    _mp_encoder: ClassVar[msgspec.msgpack.Encoder] = msgspec.msgpack.Encoder()
    _json_encoder: ClassVar[msgspec.json.Encoder] = msgspec.json.Encoder()

    @classmethod
    def _get_mp_decoder(cls) -> msgspec.msgpack.Decoder:
        # 只读取当前 class 自己的缓存，避免子类继承父类 decoder。
        attr_name = "_mp_decoder"
        decoder = cls.__dict__.get(attr_name)
        if decoder is None:
            decoder = msgspec.msgpack.Decoder(type=cls)
            setattr(cls, attr_name, decoder)
        return decoder

    @classmethod
    def _get_json_decoder(cls) -> msgspec.json.Decoder:
        # JSON decoder 与 MessagePack decoder 使用相同的 class 隔离规则。
        attr_name = "_json_decoder"
        decoder = cls.__dict__.get(attr_name)
        if decoder is None:
            decoder = msgspec.json.Decoder(type=cls)
            setattr(cls, attr_name, decoder)
        return decoder

    # ---- MsgPack ----
    def to_msgpack(self) -> bytes:
        return self._mp_encoder.encode(self)

    @classmethod
    def from_msgpack(cls, data: bytes) -> Self:
        return cls._get_mp_decoder().decode(data)

    # ---- JSON（字节/字符串）----
    def to_json_bytes(self) -> bytes:
        return self._json_encoder.encode(self)

    def to_json_str(self) -> str:
        return self.to_json_bytes().decode("utf-8")

    @classmethod
    def from_json_bytes(cls, data: bytes) -> Self:
        return cls._get_json_decoder().decode(data)

    @classmethod
    def from_json_str(cls, s: str) -> Self:
        return cls.from_json_bytes(s.encode("utf-8"))

    # ---- Python 内建结构 ----
    def to_dict(self) -> dict[str, Any]:
        return msgspec.to_builtins(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return msgspec.convert(data, type=cls)


class DataclassModelMixin:
    """
    给 dataclass 提供一致的编解码 API，以及 JSON 文件读写。
    编码：JSON 用 orjson，MsgPack 用 msgspec。解码与 MsgspecModel 一致，由 msgspec 按字段类型还原
    （枚举、时间、嵌套 dataclass 都还原成原类型）；多余的键忽略，类型不符抛 msgspec.ValidationError。
    """

    # ---- MsgPack ----
    def to_msgpack(self) -> bytes:
        return msgspec.msgpack.encode(asdict(self))  # type: ignore[arg-type]

    @classmethod
    def from_msgpack(cls, data: bytes) -> Self:
        return msgspec.msgpack.decode(data, type=cls)

    # ---- JSON（字节/字符串）----
    def to_json_bytes(self) -> bytes:
        return orjson.dumps(asdict(self))  # type: ignore[arg-type]

    def to_json_str(self) -> str:
        return self.to_json_bytes().decode("utf-8")

    @classmethod
    def from_json_bytes(cls, data: bytes) -> Self:
        return msgspec.json.decode(data, type=cls)

    @classmethod
    def from_json_str(cls, s: str) -> Self:
        return cls.from_json_bytes(s.encode("utf-8"))

    # ---- 内建结构（dict）----
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return msgspec.convert(data, type=cls)

    # ---- JSON 文件 ----
    def to_json_file(self, path: str | os.PathLike[str]) -> None:
        """写成缩进两格的 UTF-8 JSON，整体替换原文件（见 atomic_write）；父目录不存在时创建，失败抛异常。"""
        payload = orjson.dumps(asdict(self), option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE)  # type: ignore[arg-type]
        atomic_write(path, payload, follow_symlinks=True)

    async def to_json_file_async(self, path: str | os.PathLike[str]) -> None:
        await asyncio.to_thread(self.to_json_file, path)

    @classmethod
    def from_json_file(cls, path: str | os.PathLike[str]) -> Self:
        """从 JSON 文件读取。

        文件不存在抛 FileNotFoundError，要不要用默认值由调用方决定；内容不是合法 JSON 抛
        msgspec.DecodeError，字段类型不符抛 msgspec.ValidationError（它是 DecodeError 的子类）。
        """
        return msgspec.json.decode(Path(path).read_bytes(), type=cls)

    @classmethod
    async def from_json_file_async(cls, path: str | os.PathLike[str]) -> Self:
        return await asyncio.to_thread(cls.from_json_file, path)


class ModelSerializer:
    """模型序列化器"""

    @staticmethod
    def serialize(obj: Any, return_dict: bool = False) -> str | bytes | dict:
        if hasattr(obj, "__dict__"):
            data = obj.__dict__.copy()
            # 处理 SQLAlchemy 内部属性
            data.pop("_sa_instance_state", None)
            # 处理日期时间
            for k, v in data.items():
                if isinstance(v, datetime):
                    data[k] = v.isoformat()
            if return_dict:
                return data
            return orjson.dumps(data)
        return str(obj)

    @staticmethod
    def deserialize(data: bytes | dict, model_class: type) -> Any:
        if isinstance(data, bytes):
            data_dict = orjson.loads(data)
        else:
            data_dict = data
        # 处理日期时间字段
        for k, v in data_dict.items():
            if hasattr(model_class, k):
                field_type = type(getattr(model_class, k))
                if field_type == datetime:
                    data_dict[k] = datetime.fromisoformat(v)
        return model_class(**data_dict)


class PydanticModelSerializer(ModelSerializer):
    @staticmethod
    def deserialize(data: bytes | dict, model_class: type[BaseModel]) -> BaseModel:
        if isinstance(data, dict):
            return model_class.model_validate(data)
        return model_class.model_validate_json(data)

    @staticmethod
    def serialize(obj: BaseModel, return_dict: bool = False) -> str | bytes | dict:
        return obj.model_dump_json() if not return_dict else obj.model_dump()
