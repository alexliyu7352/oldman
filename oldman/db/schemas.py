"""
@author:alex
@date:2024/10/30
@time:17:07
"""

__author__ = "alex"
import uuid as uuid_pkg
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic.fields import FieldInfo
from pydantic_core.core_schema import ValidationInfo
from uuid6 import uuid7

from oldman.utils.http import sanitize_path
from oldman.utils.timezone import TimezoneManager

T = TypeVar("T")

tz_manager = TimezoneManager()


@dataclass
class PageResult(Generic[T]):  # noqa: UP046 -- the explicit Generic base is part of the public API
    """分页查询结果"""

    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size


@dataclass
class ModelField:
    field_info: FieldInfo
    name: str

    @property
    def type_(self) -> Any:
        return self.field_info.annotation

    @property
    def annotation(self):
        return self.field_info.annotation


@lru_cache
def get_schema_fields(schema) -> dict[str, ModelField]:
    return {k: ModelField(field_info=v, name=k) for k, v in schema.model_fields.items()}


def make_model_by_obj(model: type[BaseModel], obj: Any) -> BaseModel:
    return model.model_validate(obj)


class HealthCheck(BaseModel):
    name: str
    version: str
    description: str


# -------------- mixins --------------
class UUIDSchema(BaseModel):
    uuid: uuid_pkg.UUID = Field(default_factory=uuid7)


class TimestampSchema(BaseModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime | None = Field(default=None)

    @field_serializer("created_at")
    def serialize_dt(self, created_at: datetime | None, _info: Any) -> str | None:
        if created_at is not None:
            return created_at.isoformat()

        return None

    @field_serializer("updated_at")
    def serialize_updated_at(self, updated_at: datetime | None, _info: Any) -> str | None:
        if updated_at is not None:
            return updated_at.isoformat()

        return None


class PersistentDeletion(BaseModel):
    deleted_at: datetime | None = Field(default=None)
    is_deleted: bool = False

    @field_serializer("deleted_at")
    def serialize_dates(self, deleted_at: datetime | None, _info: Any) -> str | None:
        if deleted_at is not None:
            return deleted_at.isoformat()

        return None


class TimezoneModel(BaseModel):
    """处理时区转换的基础模型"""

    model_config = ConfigDict(arbitrary_types_allowed=True, json_encoders={datetime: lambda v: v.strftime("%Y-%m-%dT%H:%M:%S%z")})

    @classmethod
    def convert_datetime(cls, value: Any, info: ValidationInfo) -> Any:
        """转换所有datetime字段到用户时区"""
        if isinstance(value, datetime):
            # 确保输入时间有时区信息，没有则假定为UTC
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)

            # 从验证上下文中获取目标时区
            tz_name = info.context.get("timezone") if info.context else None
            target_tz = tz_manager.get_timezone(tz_name)

            # 转换到目标时区
            return value.astimezone(target_tz)
        return value


class UTCDatetimeMixin(BaseModel):
    """处理输入时间为UTC的Mixin类"""

    model_config = ConfigDict(arbitrary_types_allowed=True, str_strip_whitespace=True)

    @classmethod
    def ensure_utc(cls, value: Any, _info: ValidationInfo) -> Any:
        """确保所有时间字段都是UTC时间"""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value

    @classmethod
    def validate_none_strings(cls, value: Any, _info: ValidationInfo) -> Any:
        """将'null'、'none'等字符串转换为None"""
        if isinstance(value, str) and value.lower() in ("null", "none", ""):
            return None
        return value


class BaseInputModel(UTCDatetimeMixin, Generic[T]):  # noqa: UP046 -- the explicit Generic base is part of the public API
    """用于处理包含时间字段的通用响应模型"""

    data: T


# -------------- token --------------
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Annotated[int, Field(strict=True)]


class BaseResponseModel(BaseModel):
    code: int = -1
    data: Any | None = None
    message: str = ""


class TokenBlacklistBase(BaseModel):
    token: str
    expires_at: datetime


class TokenBlacklistRead(TokenBlacklistBase):
    id: int


class TokenBlacklistCreate(TokenBlacklistBase):
    pass


class TokenBlacklistUpdate(TokenBlacklistBase):
    pass


class RateLimitBase(BaseModel):
    path: Annotated[str, Field(examples=["users"])]
    limit: Annotated[int, Field(examples=[5])]
    period: Annotated[int, Field(examples=[60])]

    @field_validator("path")
    def validate_and_sanitize_path(cls, v: str) -> str:
        return sanitize_path(v)


class RateLimit(TimestampSchema, RateLimitBase):
    tier_id: int
    name: Annotated[str | None, Field(default=None, examples=["users:5:60"])]


class RateLimitRead(RateLimitBase):
    id: int
    tier_id: int
    name: str


class RateLimitCreate(RateLimitBase):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(default=None, examples=["api_v1_users:5:60"])]


class RateLimitCreateInternal(RateLimitCreate):
    tier_id: int


class RateLimitUpdate(BaseModel):
    path: str | None = Field(default=None)
    limit: int | None = None
    period: int | None = None
    name: str | None = None

    @field_validator("path")
    def validate_and_sanitize_path(cls, v: str) -> str:
        return sanitize_path(v) if v is not None else ""


class RateLimitUpdateInternal(RateLimitUpdate):
    updated_at: datetime


class RateLimitDelete(BaseModel):
    pass
