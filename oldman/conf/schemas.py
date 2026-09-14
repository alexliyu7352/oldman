"""Settings schemas for Oldman applications."""

from __future__ import annotations

import base64
import binascii
import copy
import logging
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from oldman.conf.base import YamlBaseSettings
from oldman.conf.constants import PROJECT_ROOT
from oldman.i18n.registry import LanguageRegistry, canonical_language_code


class OldmanBaseModel(BaseModel):
    """Base model for settings sections."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


class CoreConfig(OldmanBaseModel):
    """Core application config."""

    app_name: str = Field(default="oldman", description="Application name")
    data_dir: Path = Field(default=PROJECT_ROOT / "data", description="Application data directory")
    time_zone: str = Field(default="Asia/Singapore", description="Application time zone")


class LoggingConfig(OldmanBaseModel):
    """Logging level, file location and console color configuration."""

    level: int = Field(default=logging.INFO, description="Logging level")
    dir: Path = Field(default=PROJECT_ROOT / "logs", description="Log file directory")
    color: Literal["auto", "always", "never"] = Field(default="auto", description="Console color policy")

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value: object) -> object:
        """Accept legacy level names while retaining the integer runtime contract."""
        if not isinstance(value, str):
            return value

        level = logging.getLevelNamesMapping().get(value.strip().upper())
        return level if level is not None else value


class ProcessConfig(OldmanBaseModel):
    """Process lifecycle config."""

    pid_dir: Path = Field(default=PROJECT_ROOT / "pids", description="Service PID file directory")


class CSRFConfig(OldmanBaseModel):
    """Stateless Web CSRF policy."""

    ttl: int = Field(default=3600, gt=0, description="CSRF token lifetime in seconds")
    check_referer: bool = Field(
        default=True,
        description="Validate the request Referer when present",
    )
    check_url: bool = Field(
        default=False,
        description="Bind each CSRF token to its request path",
    )


class FingerprintRateLimitConfig(OldmanBaseModel):
    """One browser-fingerprint and IP rate-limit rule."""

    window: int = Field(default=60, gt=0, description="Rate-limit window in seconds")
    fp_max: int = Field(
        default=20,
        gt=0,
        description="Maximum requests per fingerprint and window",
    )
    ip_max: int = Field(
        default=40,
        gt=0,
        description="Maximum requests per IP and window",
    )


def _default_fingerprint_rate_limits() -> dict[str, FingerprintRateLimitConfig]:
    """Return independent built-in fingerprint rate-limit rules."""
    return {
        "default": FingerprintRateLimitConfig(),
        "/api/login": FingerprintRateLimitConfig(
            window=300,
            fp_max=5,
            ip_max=10,
        ),
    }


class FingerprintSecurityConfig(OldmanBaseModel):
    """Browser fingerprint encryption and anomaly policy."""

    aes_secret_key: str | None = Field(
        default=None,
        description="Base64-encoded 32-byte key shared with the browser",
    )
    timestamp_max_diff: int = Field(
        default=300 * 1000,
        gt=0,
        description="Maximum accepted browser timestamp difference in milliseconds",
    )
    rate_limits: dict[str, FingerprintRateLimitConfig] = Field(
        default_factory=_default_fingerprint_rate_limits,
        description="Endpoint-specific fingerprint and IP rate-limit rules",
    )
    max_fingerprints_per_ip: int = Field(
        default=5,
        gt=0,
        description="Maximum fingerprints associated with one IP",
    )
    max_ips_per_fingerprint: int = Field(
        default=3,
        gt=0,
        description="Maximum IPs associated with one fingerprint",
    )
    blacklist_threshold: int = Field(
        default=5,
        gt=0,
        description="Violations required before automatic blocking",
    )
    blacklist_duration: int = Field(
        default=3600,
        gt=0,
        description="Automatic blacklist duration in seconds",
    )
    violation_ttl: int = Field(
        default=3600,
        gt=0,
        description="Violation counter lifetime in seconds",
    )

    @field_validator("aes_secret_key", mode="before")
    @classmethod
    def validate_aes_secret_key(cls, value: object) -> str | None:
        """Allow settings tools to fill blanks and validate configured AES-256 keys."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("web.security.fingerprint.aes_secret_key must be a string")
        normalized = value.strip()
        if not normalized:
            return None
        try:
            decoded = base64.b64decode(normalized, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("web.security.fingerprint.aes_secret_key must be valid base64") from None
        if len(decoded) != 32:
            raise ValueError("web.security.fingerprint.aes_secret_key must encode exactly 32 bytes")
        return normalized

    @model_validator(mode="after")
    def validate_default_rate_limit(self) -> FingerprintSecurityConfig:
        """Require the fallback rule consumed by every unspecified endpoint."""
        if "default" not in self.rate_limits:
            raise ValueError("web.security.fingerprint.rate_limits must define 'default'")
        return self


class WebSecurityConfig(OldmanBaseModel):
    """Central Web signing, token, CSRF, and browser-fingerprint settings."""

    secret_key: str | None = Field(
        default=None,
        description="Server-only root key for purpose-separated Web secrets",
    )
    token_expire_time: int = Field(
        default=60 * 60 * 24,
        gt=0,
        description="Authentication token lifetime in seconds",
    )
    csrf: CSRFConfig = Field(
        default_factory=CSRFConfig,
        description="Stateless CSRF policy",
    )
    fingerprint: FingerprintSecurityConfig = Field(
        default_factory=FingerprintSecurityConfig,
        description="Browser fingerprint security policy",
    )

    @field_validator("secret_key", mode="before")
    @classmethod
    def validate_secret_key(cls, value: object) -> str | None:
        """Allow settings tools to fill blanks and reject weak configured roots."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("web.security.secret_key must be a string")
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) < 32:
            raise ValueError("web.security.secret_key must contain at least 32 characters")
        return normalized


class SessionConfig(OldmanBaseModel):
    """Optional Redis-backed Web session configuration."""

    enabled: bool = Field(default=False, description="Install Web session middleware")
    redis_alias: str = Field(default="SESSION", min_length=1, description="Named Redis connection used by sessions")
    expiry: int = Field(default=60 * 60 * 24 * 30, gt=0, description="Default session lifetime in seconds")
    prefix: str = Field(default="session:", min_length=1, description="Redis session key prefix")
    user_prefix: str = Field(default="user_session:", min_length=1, description="Redis user-session index prefix")
    cookie_name: str = Field(default="session_id", min_length=1, description="Browser session cookie name")
    cookie_domain: str | None = Field(default=None, description="Optional browser session cookie domain")
    cookie_httponly: bool = Field(default=True, description="Hide the session cookie from browser scripts")
    cookie_secure: bool = Field(default=False, description="Restrict the session cookie to HTTPS")
    cookie_samesite: Literal["Lax", "Strict", "None"] | None = Field(
        default="Lax",
        description="Browser SameSite policy for the session cookie",
    )


class SSEConfig(OldmanBaseModel):
    """Optional distributed browser event configuration."""

    enabled: bool = Field(default=False, description="Enable Redis-backed distributed SSE delivery")
    redis_alias: str = Field(default="SSE", min_length=1, description="Named Redis connection used by SSE")
    channel_prefix: str = Field(default="", description="Project and environment specific Redis channel prefix")
    heartbeat_interval: float = Field(default=15.0, gt=0, description="Idle heartbeat interval in seconds")
    session_check_interval: float = Field(
        default=30.0,
        gt=0,
        description="Authenticated session validation interval in seconds",
    )
    queue_size: int = Field(default=100, gt=0, description="Default bounded SSE connection queue size")
    max_message_size: int = Field(default=65536, gt=0, description="Maximum encoded Redis event size in bytes")

    @model_validator(mode="after")
    def validate_distributed_settings(self) -> SSEConfig:
        """Require an explicit channel namespace only when Redis delivery is enabled."""
        if self.enabled and not self.channel_prefix.strip():
            raise ValueError("web.sse.channel_prefix must not be blank when distributed SSE is enabled")
        return self


class TemplateConfig(OldmanBaseModel):
    """Template config."""

    dir: Path = Field(default=PROJECT_ROOT / "templates", description="Server-rendered template directory")


class StaticConfig(OldmanBaseModel):
    """Static assets config."""

    dir: Path = Field(default=PROJECT_ROOT / "static", description="Static source directory")
    root: str = Field(default=str(PROJECT_ROOT / "static"), description="Static file root")
    url: str = Field(default="/static/", description="Static URL prefix")


class I18nLanguageConfig(OldmanBaseModel):
    """Optional user overrides for one canonical language definition."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    aliases: list[str] = Field(default_factory=list, description="Accepted BCP 47 language aliases")
    name: str = Field(default="", description="Language menu display name override")
    flag: str = Field(default="", description="Language menu flag asset override")

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: list[str]) -> list[str]:
        """Validate and canonicalize explicitly configured aliases."""
        normalized = [canonical_language_code(alias) for alias in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("i18n language aliases must not contain duplicates")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Reject an explicitly blank display name."""
        if not value.strip():
            raise ValueError("i18n language name must not be blank")
        return value.strip()


def _default_i18n_languages() -> dict[str, I18nLanguageConfig]:
    """Return the minimal standalone language definition."""
    return {"en": I18nLanguageConfig()}


class I18nConfig(OldmanBaseModel):
    """Internationalization config."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    use_i18n: bool = Field(default=False, description="Enable internationalization")
    use_i18n_path: bool = Field(default=False, description="Enable language-prefixed routes")
    default_language: str = Field(default="en", description="Default language code")
    languages: dict[str, I18nLanguageConfig] = Field(
        default_factory=_default_i18n_languages,
        description="Canonical project language definitions",
    )

    @field_validator("languages", mode="before")
    @classmethod
    def normalize_language_keys(cls, value: object) -> object:
        """Normalize configured canonical codes before building child models."""
        if not isinstance(value, Mapping):
            return value

        normalized: dict[str, object] = {}
        for raw_code, config in value.items():
            code = canonical_language_code(str(raw_code))
            if code in normalized:
                raise ValueError(f"i18n.languages contains duplicate canonical code {code!r}")
            normalized[code] = config
        return normalized

    @field_validator("default_language", mode="before")
    @classmethod
    def normalize_default_language(cls, value: object) -> str:
        """Require one standard language tag before resolving project aliases."""
        if not isinstance(value, str):
            raise TypeError("i18n.default_language must be a string")
        return canonical_language_code(value)

    @field_serializer("languages")
    def serialize_language_overrides(
        self,
        languages: dict[str, I18nLanguageConfig],
    ) -> dict[str, dict[str, object]]:
        """Preserve compact user overrides instead of materializing runtime defaults."""
        return {code: language.model_dump(mode="json", exclude_unset=True) for code, language in languages.items()}

    @model_validator(mode="after")
    def validate_language_contract(self) -> I18nConfig:
        """Resolve the default language and reject ambiguous project aliases."""
        if self.use_i18n_path and not self.use_i18n:
            raise ValueError("i18n.use_i18n_path requires i18n.use_i18n=true")
        if self.use_i18n and not self.languages:
            raise ValueError("i18n.languages must not be empty when i18n is enabled")

        registry = LanguageRegistry(self.languages)
        resolved_default = registry.resolve(self.default_language)
        if resolved_default:
            self.default_language = resolved_default
        elif self.use_i18n:
            raise ValueError("i18n.default_language must resolve to one entry in i18n.languages")
        return self


class DatabaseConfig(OldmanBaseModel):
    """Database config."""

    url: str | None = Field(default=None, description="SQLAlchemy async database URL")
    echo: bool | None = Field(default=None, description="Override SQLAlchemy engine echo; null follows web.debug")
    enable_sql_logging: bool = Field(default=False, description="Enable SQL query tracking and performance summaries")


class RedisConnectionConfig(OldmanBaseModel):
    """One named Redis connection and its redis-py pool options."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    redis_url: str = Field(min_length=1, description="Redis connection URL")
    decode_responses: bool = Field(default=True, description="Decode Redis responses to strings")
    max_connections: int = Field(default=1024, gt=0, description="Maximum Redis connection pool size")
    health_check_interval: int = Field(default=30, ge=0, description="Redis connection health-check interval")
    retry_attempts: int = Field(default=3, ge=0, description="Redis connection retry attempts")
    retry_on_timeout: bool = Field(default=True, description="Retry Redis operations that time out")
    protocol: int = Field(default=2, ge=2, le=3, description="Redis RESP protocol version")
    backoff_base: float = Field(default=0.1, ge=0, description="Redis retry exponential-backoff base")
    backoff_cap: float = Field(default=2.0, ge=0, description="Redis retry exponential-backoff cap")
    socket_keepalive: bool = Field(default=True, description="Enable TCP keepalive for Redis TCP connections")
    socket_keepalive_idle: int = Field(default=60, gt=0, description="TCP keepalive idle time")
    socket_keepalive_interval: int = Field(default=10, gt=0, description="TCP keepalive probe interval")
    socket_keepalive_count: int = Field(default=3, gt=0, description="TCP keepalive probe count")
    __pydantic_extra__: dict[str, Any] = Field(init=False)

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        """Reject blank Redis URLs while retaining the configured value."""
        if not value.strip():
            raise ValueError("redis_url must not be blank")
        return value

    @model_validator(mode="after")
    def validate_connection_options(self) -> RedisConnectionConfig:
        """Allow only prefixed redis-py extensions without duplicate meanings."""
        declared_fields = set(type(self).model_fields) | {
            "connection_pool",
            "retry",
            "socket_keepalive_options",
            "url",
        }
        for field_name in self.__pydantic_extra__ or {}:
            if not field_name.startswith("connection_") or field_name == "connection_":
                raise ValueError(f"unknown Redis option {field_name!r}; redis-py extensions require a connection_ prefix")
            option_name = field_name.removeprefix("connection_")
            if option_name in declared_fields:
                raise ValueError(f"connection option {option_name!r} duplicates the declared {option_name!r} field")
        return self

    @property
    def connection_options(self) -> dict[str, Any]:
        """Return redis-py extension options without their settings prefix."""
        return {field_name.removeprefix("connection_"): value for field_name, value in (self.__pydantic_extra__ or {}).items()}

    def client_options(self, *, decode_responses: bool | None = None) -> dict[str, Any]:
        """Return constructor options for the concrete async Redis client."""
        values = self.model_dump()
        if decode_responses is not None:
            values["decode_responses"] = decode_responses
        return values


_BUILTIN_REDIS_CONNECTIONS: dict[str, dict[str, str]] = {
    "DEFAULT": {"redis_url": "unix:///var/run/redis/redis.sock?db=3"},
    "CACHE": {"redis_url": "redis://localhost:6379/2"},
    "SESSION": {"redis_url": "redis://localhost:6379/5"},
}


def _default_redis_connection(name: str) -> RedisConnectionConfig:
    """Build one independent built-in Redis connection config."""
    return RedisConnectionConfig.model_validate(copy.deepcopy(_BUILTIN_REDIS_CONNECTIONS[name]))


class RedisConfig(OldmanBaseModel, Mapping[str, RedisConnectionConfig]):
    """Case-sensitive mapping of named Redis connection configs."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    DEFAULT: RedisConnectionConfig = Field(
        default_factory=lambda: _default_redis_connection("DEFAULT"),
        description="Default Redis connection",
    )
    CACHE: RedisConnectionConfig = Field(
        default_factory=lambda: _default_redis_connection("CACHE"),
        description="Redis connection used by the Redis cache backend",
    )
    SESSION: RedisConnectionConfig = Field(
        default_factory=lambda: _default_redis_connection("SESSION"),
        description="Redis connection used by Web sessions",
    )
    __pydantic_extra__: dict[str, RedisConnectionConfig] = Field(init=False)

    @model_validator(mode="before")
    @classmethod
    def merge_builtin_connections(cls, value: Any) -> Any:
        """Merge partial built-in aliases without inventing URLs for custom aliases."""
        if isinstance(value, cls) or not isinstance(value, Mapping):
            return value
        merged = copy.deepcopy(dict(value))
        for name, defaults in _BUILTIN_REDIS_CONNECTIONS.items():
            configured = merged.get(name)
            if isinstance(configured, Mapping):
                merged[name] = {**copy.deepcopy(defaults), **copy.deepcopy(dict(configured))}
        return merged

    @model_validator(mode="after")
    def validate_connection_names(self) -> RedisConfig:
        """Reject empty custom connection names."""
        for name in self.__pydantic_extra__ or {}:
            if not name.strip():
                raise ValueError("Redis connection names must not be blank")
        return self

    def __getitem__(self, name: str) -> RedisConnectionConfig:
        if name in type(self).model_fields:
            return cast(RedisConnectionConfig, getattr(self, name))
        try:
            return (self.__pydantic_extra__ or {})[name]
        except KeyError:
            raise KeyError(name) from None

    def __iter__(self) -> Iterator[str]:
        yield from type(self).model_fields
        yield from self.__pydantic_extra__ or {}

    def __len__(self) -> int:
        return len(type(self).model_fields) + len(self.__pydantic_extra__ or {})


class RedisCacheConfig(OldmanBaseModel):
    """Configuration for the Redis-backed cache implementation."""

    client: str = Field(default="CACHE", min_length=1, description="Named Redis client used by the cache")
    namespace: str = Field(default="main", min_length=1, description="Redis cache key namespace")
    serializer: str = Field(default="pickle", min_length=1, description="Redis cache serializer name")


class NATSConnectionConfig(OldmanBaseModel):
    """One native NATS connection; validation never reads certificates or connects."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    nats_url: str = Field(min_length=1, repr=False, description="NATS URL, optionally containing encoded credentials")
    connect_timeout: float = Field(default=2, gt=0, allow_inf_nan=False, description="NATS connection attempt timeout in seconds")
    reconnect_time_wait: float = Field(default=2, gt=0, allow_inf_nan=False, description="Delay between native NATS reconnect attempts")
    tls_ca_file: Path | None = Field(default=None, description="Trusted NATS server CA file; null uses system trust")
    tls_cert_file: Path | None = Field(default=None, description="Optional client certificate for mutual TLS")
    tls_key_file: Path | None = Field(default=None, description="Private key paired with the client certificate")
    credentials_file: Path | None = Field(default=None, description="NATS .creds identity file, exclusive with URL credentials")

    @model_validator(mode="after")
    def validate_connection(self) -> NATSConnectionConfig:
        """Reject ambiguous endpoints and authentication without exposing secrets."""
        try:
            endpoint = urlsplit(self.nats_url)
            port = endpoint.port
        except ValueError:
            raise ValueError("invalid nats_url endpoint") from None
        if (
            self.nats_url != self.nats_url.strip()
            or any(character.isspace() for character in self.nats_url)
            or endpoint.scheme not in {"nats", "tls"}
            or not endpoint.hostname
            or port == 0
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("nats_url must be a nats:// or tls:// host URL without query or fragment")
        if (self.tls_cert_file is None) != (self.tls_key_file is None):
            raise ValueError("tls_cert_file and tls_key_file must be configured together")
        if self.credentials_file is not None and endpoint.username is not None:
            raise ValueError("credentials_file cannot be combined with URL credentials")
        return self


class NATSConfig(OldmanBaseModel, Mapping[str, NATSConnectionConfig]):
    """Case-sensitive named NATS connections, matching the Redis mapping convention."""

    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)

    DEFAULT: NATSConnectionConfig = Field(
        default_factory=lambda: NATSConnectionConfig(nats_url="nats://localhost:4222"),
        description="Default NATS connection",
    )
    __pydantic_extra__: dict[str, NATSConnectionConfig] = Field(init=False)

    @model_validator(mode="before")
    @classmethod
    def merge_default_connection(cls, value: Any) -> Any:
        """Retain the built-in URL when only DEFAULT connection options are supplied."""
        if isinstance(value, Mapping) and isinstance(value.get("DEFAULT"), Mapping):
            return {**value, "DEFAULT": {"nats_url": "nats://localhost:4222", **value["DEFAULT"]}}
        return value

    @model_validator(mode="after")
    def validate_connection_names(self) -> NATSConfig:
        """Reject blank aliases without silently normalizing deployment names."""
        if any(not name.strip() for name in self.__pydantic_extra__ or {}):
            raise ValueError("NATS connection names must not be blank")
        return self

    def __getitem__(self, name: str) -> NATSConnectionConfig:
        """Resolve a declared or custom alias without creating a connection."""
        if name in type(self).model_fields:
            return cast(NATSConnectionConfig, getattr(self, name))
        try:
            return (self.__pydantic_extra__ or {})[name]
        except KeyError:
            raise KeyError(name) from None

    def __iter__(self) -> Iterator[str]:
        """Enumerate built-in and explicitly supplied aliases."""
        yield from type(self).model_fields
        yield from self.__pydantic_extra__ or {}

    def __len__(self) -> int:
        """Return the number of independently configured endpoints."""
        return len(type(self).model_fields) + len(self.__pydantic_extra__ or {})


class NATSBusConfig(OldmanBaseModel):
    """Core event/RPC lifecycle, independent of named transports and Taskiq."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, description="Enable the process-local event/RPC connection")
    nats_alias: str = Field(default="DEFAULT", min_length=1, description="Named NATS connection for events and RPC")
    consume: bool = Field(default=False, description="Receive App events in a long-running Web or Simple service")
    namespace: str | None = Field(default=None, description="Shared project/environment namespace; required when enabled")
    peer_id: str | None = Field(default=None, description="Explicit local identity for directed subscriptions and source headers")
    serializer_mode: Literal["msgpack", "msgspec_json"] = Field(default="msgpack", description="Bytes codec agreed by both ends")
    startup_timeout: float = Field(default=30, gt=0, allow_inf_nan=False, description="Total seconds allowed to establish the sending connection")
    graceful_timeout: float = Field(default=10, gt=0, allow_inf_nan=False, description="Shared normal-completion wait for active handlers at shutdown")

    @field_validator("namespace", "peer_id")
    @classmethod
    def validate_address_name(cls, value: str | None) -> str | None:
        """Keep explicit identities intact; absent is different from an invalid name."""
        if value is not None and re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError("NATS bus names must contain only ASCII letters, digits, underscores or hyphens")
        return value

    @model_validator(mode="after")
    def validate_enabled_namespace(self) -> NATSBusConfig:
        """Disabled services may retain receive settings without opening facilities."""
        if self.enabled and self.namespace is None:
            raise ValueError("nats_bus.namespace is required when NATS bus is enabled")
        return self


def validate_taskiq_name(value: str) -> str:
    """Keep each task namespace/queue a single safe NATS subject component."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Taskiq names must contain only ASCII letters, digits, underscores or hyphens")
    return value


class TaskiqConfig(OldmanBaseModel):
    """Distributed task limits, separate from fixed local Worker configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, description="Explicitly enable Taskiq for this service")
    namespace: str | None = Field(default=None, description="Shared task namespace; required when enabled")
    nats_alias: str = Field(default="DEFAULT", min_length=1, description="Named NATS connection for task transport")
    redis_alias: str = Field(default="DEFAULT", min_length=1, description="Named Redis connection for results and schedules")
    consume_queues: list[str] = Field(default_factory=lambda: ["default"], min_length=1, description="Queues sharing this service's execution processes")
    workers: int = Field(default=2, gt=0, description="Number of task execution processes")
    max_async_tasks: int = Field(default=100, gt=0, description="Concurrent tasks per process, shared by all queues")
    max_prefetch: int = Field(default=0, ge=0, description="Extra Receiver admission slots beyond max_async_tasks; zero adds none")
    startup_timeout: float = Field(default=30, gt=0, allow_inf_nan=False, description="Total seconds allowed for one initialization attempt")
    startup_attempts: int = Field(default=3, gt=0, description="Initial attempts per execution position, including the first")
    shutdown_timeout: float = Field(default=5, gt=0, allow_inf_nan=False, description="Resource cleanup budget in seconds, after business work")
    stop_timeout: float = Field(default=60, gt=0, allow_inf_nan=False, description="Total service stop deadline before killing its process group")
    ack_wait: float = Field(default=60, gt=0, allow_inf_nan=False, description="Consumer acknowledgement wait; renewal runs every third of this interval")
    publish_timeout: float = Field(default=5, gt=0, allow_inf_nan=False, description="One publish confirmation or broadcast flush timeout")
    ack_timeout: float = Field(default=5, gt=0, allow_inf_nan=False, description="One acknowledged completion timeout")
    duplicate_window: float = Field(default=120, gt=0, allow_inf_nan=False, description="Stream publish-deduplication window in seconds")
    result_ex_time: int = Field(default=86400, gt=0, description="Result retention in seconds from its write, not its last read")
    stream_max_bytes: int = Field(default=-1, description="Stream byte limit; -1 uses the server/account capacity")
    stream_replicas: Literal[1, 3, 5] = Field(default=1, description="JetStream replicas; the deployment must provide enough nodes")
    max_ack_pending: int = Field(default=1000, gt=0, description="Unacknowledged tasks across all consumers of one queue")
    schedule_update_interval: int = Field(default=5, gt=0, description="Seconds between native schedule-source refreshes")

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, value: str | None) -> str | None:
        """An omitted disabled namespace is valid; supplied names are always checked."""
        return validate_taskiq_name(value) if value is not None else None

    @field_validator("consume_queues")
    @classmethod
    def validate_queues(cls, values: list[str]) -> list[str]:
        """One subscription per queue; preserve the operator's exact queue names."""
        for value in values:
            validate_taskiq_name(value)
        if len(values) != len(set(values)):
            raise ValueError("consume_queues must not contain duplicate queues")
        return values

    @model_validator(mode="after")
    def validate_limits(self) -> TaskiqConfig:
        """Check related values without contacting a task service."""
        if self.enabled and self.namespace is None:
            raise ValueError("taskiq.namespace is required when Taskiq is enabled")
        if self.stream_max_bytes != -1 and self.stream_max_bytes <= 0:
            raise ValueError("stream_max_bytes must be -1 or a positive byte limit")
        if self.duplicate_window < 2 * self.publish_timeout:
            raise ValueError("duplicate_window must cover two publish_timeout intervals")
        return self


class HttpClientConfig(OldmanBaseModel):
    """HTTP client config."""

    max_connections: int = Field(default=300, description="Maximum HTTP connection pool size")
    user_agent: str = Field(default="okhttp/3.8.7", description="Default outbound HTTP user agent")


class StorageBackendConfig(OldmanBaseModel):
    """One importable storage backend and its backend-specific options."""

    backend: str = Field(description="Dotted import path of the storage backend")
    options: dict[str, Any] = Field(default_factory=dict, description="Storage backend options")

    @field_validator("backend")
    @classmethod
    def validate_backend_path(cls, value: str) -> str:
        """Strip and validate a module attribute import path."""
        normalized = value.strip()
        segments = normalized.split(".")
        if len(segments) < 2 or not all(segment.isidentifier() for segment in segments):
            raise ValueError("storage backend must be a dotted import path")
        return normalized


def _default_storage_backend() -> StorageBackendConfig:
    """Build an independent filesystem-backed default storage config."""
    return StorageBackendConfig(
        backend="oldman.storage.backends.filesystem.FileSystemStorage",
        options={"location": PROJECT_ROOT / "media"},
    )


class StoragesConfig(OldmanBaseModel, Mapping[str, StorageBackendConfig]):
    """Mapping of the default storage and dynamically named storage aliases."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    default: StorageBackendConfig = Field(
        default_factory=_default_storage_backend,
        description="Default file storage backend",
    )
    __pydantic_extra__: dict[str, StorageBackendConfig] = Field(init=False)

    @model_validator(mode="after")
    def validate_storage_aliases(self) -> StoragesConfig:
        """Reject blank aliases and the reserved in-memory backend alias."""
        for name in self.__pydantic_extra__ or {}:
            if not name.strip():
                raise ValueError("storage aliases must not be blank")
            if name.strip() == "memory":
                raise ValueError("storage alias 'memory' is reserved")
        return self

    def __getitem__(self, name: str) -> StorageBackendConfig:
        if name in type(self).model_fields:
            return cast(StorageBackendConfig, getattr(self, name))
        try:
            return (self.__pydantic_extra__ or {})[name]
        except KeyError:
            raise KeyError(name) from None

    def __iter__(self) -> Iterator[str]:
        yield from type(self).model_fields
        yield from self.__pydantic_extra__ or {}

    def __len__(self) -> int:
        return len(type(self).model_fields) + len(self.__pydantic_extra__ or {})


class MediaConfig(OldmanBaseModel):
    """Media storage and URL config."""

    storage: str = Field(default="default", description="Named storage used for media files")
    url: str = Field(default="/media/", description="Media URL prefix")


class ProxyConfig(OldmanBaseModel):
    """Media proxy runtime config."""

    connect_timeout: int = Field(default=5, description="Proxy connection timeout in seconds")
    read_timeout: int = Field(default=10, description="Proxy read timeout in seconds")
    debug_proxy: str | None = Field(default="http://127.0.0.1:8118", description="Debug-only outbound proxy URL")


class FrontendConfig(OldmanBaseModel):
    """Frontend build and dev-server config."""

    vite_dev_server_url: str = Field(default="http://localhost:5173", description="Vite development server URL")


class MessagesConfig(OldmanBaseModel):
    """Cookie-backed one-time Web message configuration."""

    enabled: bool = Field(default=False, description="Install one-time Web messages")


class WebConfig(OldmanBaseModel):
    """Web server and browser-facing service config."""

    listen_host: str = Field(default="::", description="Web server listen host")
    listen_port: int = Field(default=17998, description="Web server listen port")
    debug: bool = Field(default=False, description="Enable web debug mode")
    auto_reload: bool = Field(default=False, description="Enable source auto reload")
    workers: int = Field(default=1, description="Web server worker count")
    access_log: bool = Field(default=False, description="Enable HTTP access logging")
    response_timeout: int = Field(default=120, description="Sanic response timeout in seconds")
    request_timeout: int = Field(default=120, description="Sanic request timeout in seconds")
    keep_alive_timeout: int = Field(default=120, description="Sanic keep-alive timeout in seconds")
    real_ip_header: str = Field(default="X-Real-IP", description="Header containing the client IP address")
    proxies_count: int | None = Field(
        default=None,
        description="Number of trusted proxies that append to X-Forwarded-For; unset ignores that header",
    )
    forwarded_secret: str | None = Field(
        default=None,
        description="Secret a trusted proxy places in the RFC 7239 Forwarded header; unset ignores that header",
    )
    fallback_error_format: Literal["auto", "html", "json", "text"] = Field(
        default="auto",
        description="Sanic fallback error response format",
    )
    websocket_max_size: int = Field(default=2**20, description="Maximum WebSocket message size in bytes")
    websocket_ping_interval: int = Field(default=5, description="WebSocket ping interval in seconds")
    websocket_ping_timeout: int = Field(default=20, description="WebSocket ping timeout in seconds")
    domain: str = Field(default="http://localhost:17998", description="Public application domain")
    security: WebSecurityConfig = Field(
        default_factory=WebSecurityConfig,
        description="Web security settings",
    )
    session: SessionConfig = Field(default_factory=SessionConfig, description="Web session settings")
    messages: MessagesConfig = Field(default_factory=MessagesConfig, description="One-time Web message settings")
    sse: SSEConfig = Field(default_factory=SSEConfig, description="Server-sent event settings")
    template: TemplateConfig = Field(default_factory=TemplateConfig, description="Template settings")
    static: StaticConfig = Field(default_factory=StaticConfig, description="Static asset settings")
    media: MediaConfig = Field(default_factory=MediaConfig, description="Media asset settings")
    frontend: FrontendConfig = Field(default_factory=FrontendConfig, description="Frontend build settings")


class DefaultSettings(YamlBaseSettings):
    """Complete runtime settings schema."""

    # Nested authentication validation must not print input mappings with credentials.
    model_config = ConfigDict(hide_input_in_errors=True)

    apps: tuple[str, ...] = Field(default=(), description="Installed App package paths")
    core: CoreConfig = Field(default_factory=CoreConfig, description="Core application settings")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="Logging settings")
    process: ProcessConfig = Field(default_factory=ProcessConfig, description="Process lifecycle settings")
    web: WebConfig = Field(default_factory=WebConfig, description="Web server settings")
    i18n: I18nConfig = Field(default_factory=I18nConfig, description="Internationalization settings")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig, description="Database settings")
    redis: RedisConfig = Field(default_factory=RedisConfig, description="Named Redis connection settings")
    nats: NATSConfig = Field(default_factory=NATSConfig, description="Named NATS connection settings")
    nats_bus: NATSBusConfig = Field(default_factory=NATSBusConfig, description="Core NATS event and RPC settings")
    taskiq: TaskiqConfig = Field(default_factory=TaskiqConfig, description="Distributed task settings")
    cache: RedisCacheConfig = Field(default_factory=RedisCacheConfig, description="Redis cache settings")
    http_client: HttpClientConfig = Field(default_factory=HttpClientConfig, description="HTTP client settings")
    storages: StoragesConfig = Field(default_factory=StoragesConfig, description="Named file storage settings")
    proxy: ProxyConfig = Field(default_factory=ProxyConfig, description="Media proxy settings")

    @model_validator(mode="after")
    def validate_taskiq_connections(self) -> DefaultSettings:
        """Enabled task services must resolve both explicit connection aliases."""
        if self.taskiq.enabled:
            if self.taskiq.nats_alias not in self.nats:
                raise ValueError("taskiq.nats_alias does not identify a configured NATS connection")
            if self.taskiq.redis_alias not in self.redis:
                raise ValueError("taskiq.redis_alias does not identify a configured Redis connection")
        return self

    @model_validator(mode="after")
    def validate_nats_bus_connection(self) -> DefaultSettings:
        """Resolve the enabled bus alias without reading credentials or connecting."""
        if self.nats_bus.enabled and self.nats_bus.nats_alias not in self.nats:
            raise ValueError("nats_bus.nats_alias does not identify a configured NATS connection")
        return self

    @model_validator(mode="before")
    @classmethod
    def validate_explicit_default_storage(cls, value: Any) -> Any:
        """Require an explicit default backend whenever storages is declared."""
        if isinstance(value, Mapping) and "storages" in value:
            configured = value["storages"]
            if not isinstance(configured, Mapping) or "default" not in configured:
                raise ValueError("explicit storages settings must define 'default'")
        return value
