from __future__ import annotations

import threading
from dataclasses import asdict
from datetime import datetime
from typing import Any, ClassVar, TypeVar

import msgspec
import orjson
from pydantic import BaseModel

T = TypeVar("T")

_tls = threading.local()


def _get_mp_encoder() -> msgspec.msgpack.Encoder:
    enc = getattr(_tls, "mp_enc", None)
    if enc is None:
        enc = _tls.mp_enc = msgspec.msgpack.Encoder()
    return enc


def _get_json_encoder() -> msgspec.json.Encoder:
    enc = getattr(_tls, "json_enc", None)
    if enc is None:
        enc = _tls.json_enc = msgspec.json.Encoder()
    return enc


def _get_mp_decoder(cls: type) -> msgspec.msgpack.Decoder:
    decs = getattr(_tls, "mp_decs", None)
    if decs is None:
        decs = _tls.mp_decs = {}
    dec = decs.get(cls)
    if dec is None:
        dec = decs[cls] = msgspec.msgpack.Decoder(type=cls)  # ← 现在在“真正用到时”才创建
    return dec


def _get_json_decoder(cls: type) -> msgspec.json.Decoder:
    decs = getattr(_tls, "json_decs", None)
    if decs is None:
        decs = _tls.json_decs = {}
    dec = decs.get(cls)
    if dec is None:
        dec = decs[cls] = msgspec.json.Decoder(type=cls)
    return dec


# ---------- 基类：msgspec.Struct 版（高性能） ----------
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
    def from_msgpack(cls: type[T], data: bytes) -> T:
        return cls._get_mp_decoder().decode(data)  # pyright: ignore[reportAttributeAccessIssue] -- decoder exists on MsgspecModel subclasses

    # ---- JSON（字节/字符串）----
    def to_json_bytes(self) -> bytes:
        return self._json_encoder.encode(self)

    def to_json_str(self) -> str:
        return self.to_json_bytes().decode("utf-8")

    @classmethod
    def from_json_bytes(cls: type[T], data: bytes) -> T:
        return cls._get_json_decoder().decode(data)  # pyright: ignore[reportAttributeAccessIssue] -- decoder exists on MsgspecModel subclasses

    @classmethod
    def from_json_str(cls: type[T], s: str) -> T:
        return cls.from_json_bytes(s.encode("utf-8"))  # pyright: ignore[reportAttributeAccessIssue] -- method exists on MsgspecModel subclasses

    # ---- Python 内建结构 ----
    def to_dict(self) -> dict[str, Any]:
        return msgspec.to_builtins(self)

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        return msgspec.convert(data, type=cls)


class MsgspecSafeModel(msgspec.Struct):
    # ---- MsgPack ----
    def to_msgpack(self) -> bytes:
        return _get_mp_encoder().encode(self)

    @classmethod
    def from_msgpack(cls: type[T], data: bytes) -> T:
        return _get_mp_decoder(cls).decode(data)

    # ---- JSON ----
    def to_json_bytes(self) -> bytes:
        return _get_json_encoder().encode(self)

    def to_json_str(self) -> str:
        return self.to_json_bytes().decode("utf-8")

    @classmethod
    def from_json_bytes(cls: type[T], data: bytes) -> T:
        return _get_json_decoder(cls).decode(data)

    @classmethod
    def from_json_str(cls: type[T], s: str) -> T:
        return cls.from_json_bytes(s.encode("utf-8"))  # pyright: ignore[reportAttributeAccessIssue] -- method exists on MsgspecSafeModel subclasses

    # ---- Python 内建结构 ----
    def to_dict(self) -> dict[str, Any]:
        return msgspec.to_builtins(self)

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        return msgspec.convert(data, type=cls)


# ---------- 混入：dataclass 版（标准库） ----------
class DataclassModelMixin:
    """
    给 dataclass 提供一致的编解码 API。
    JSON 用 orjson；MsgPack 走 msgspec 对内建类型的快速编解码。
    """

    # ---- MsgPack ----
    def to_msgpack(self) -> bytes:
        return msgspec.msgpack.encode(asdict(self))  # type: ignore[arg-type]

    @classmethod
    def from_msgpack(cls: type[T], data: bytes) -> T:
        d = msgspec.msgpack.decode(data, type=dict)
        return cls(**d)  # type: ignore[arg-type]

    # ---- JSON（字节/字符串）----
    def to_json_bytes(self) -> bytes:
        return orjson.dumps(asdict(self))  # type: ignore[arg-type]

    def to_json_str(self) -> str:
        return self.to_json_bytes().decode("utf-8")

    @classmethod
    def from_json_bytes(cls: type[T], data: bytes) -> T:
        d = orjson.loads(data)
        return cls(**d)  # type: ignore[arg-type]

    @classmethod
    def from_json_str(cls: type[T], s: str) -> T:
        return cls.from_json_bytes(s.encode("utf-8"))  # pyright: ignore[reportAttributeAccessIssue] -- method exists on DataclassModelMixin subclasses

    # ---- 内建结构（dict）----
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        return cls(**data)  # type: ignore[arg-type]


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
