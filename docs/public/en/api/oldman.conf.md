# `oldman.conf`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Application settings bootstrap and public configuration API.

Import with `from oldman.conf import <name>`.

## `DefaultSettings`

class · defined in `oldman.conf.schemas`

```python
class DefaultSettings(YamlBaseSettings)
```

Complete runtime settings schema.

Members:

- `apps: tuple[str, ...] = Field(default=(), description='Installed App package paths')`
- `core: CoreConfig = Field(default_factory=CoreConfig, description='Core application settings')`
- `logging: LoggingConfig = Field(default_factory=LoggingConfig, description='Logging settings')`
- `process: ProcessConfig = Field(default_factory=ProcessConfig, description='Process lifecycle settings')`
- `web: WebConfig = Field(default_factory=WebConfig, description='Web server settings')`
- `i18n: I18nConfig = Field(default_factory=I18nConfig, description='Internationalization settings')`
- `database: DatabaseConfig = Field(default_factory=DatabaseConfig, description='Database settings')`
- `redis: RedisConfig = Field(default_factory=RedisConfig, description='Named Redis connection settings')`
- `nats: NATSConfig = Field(default_factory=NATSConfig, description='Named NATS connection settings')`
- `nats_bus: NATSBusConfig = Field(default_factory=NATSBusConfig, description='Core NATS event and RPC settings')`
- `taskiq: TaskiqConfig = Field(default_factory=TaskiqConfig, description='Distributed task settings')`
- `cache: RedisCacheConfig = Field(default_factory=RedisCacheConfig, description='Redis cache settings')`
- `http_client: HttpClientConfig = Field(default_factory=HttpClientConfig, description='HTTP client settings')`
- `storages: StoragesConfig = Field(default_factory=StoragesConfig, description='Named file storage settings')`
- `mail: MailConfig = Field(default_factory=MailConfig, description='Outgoing mail settings')`
- `proxy: ProxyConfig = Field(default_factory=ProxyConfig, description='Media proxy settings')`
- `def validate_taskiq_connections() -> DefaultSettings` — Enabled task services must resolve both explicit connection aliases.
- `def validate_cache_connection() -> DefaultSettings` — Resolve the cache alias up front instead of at the first cache call.
- `def validate_nats_bus_connection() -> DefaultSettings` — Resolve the enabled bus alias without reading credentials or connecting.
- `classmethod def validate_explicit_default_storage(value: Any) -> Any` — Require an explicit default backend whenever storages is declared.

## `PROJECT_BASE_PATH`

value · defined in `oldman.conf`

```python
PROJECT_BASE_PATH = constants.BASE_PATH
```

## `settings`

value · defined in `oldman.conf`

```python
settings: DefaultSettings
```

## `SettingsFileMissingError`

class · defined in `oldman.conf.base`

```python
class SettingsFileMissingError(RuntimeError)
```

Raised when the selected YAML settings source cannot find its file.

## `SettingsManager`

class · defined in `oldman.conf.manager`

```python
class SettingsManager
```

Own one service definition, YAML file, Settings and App Registry.

Constructor:

```python
SettingsManager(settings_class: type[T_Settings], service_definition: ServiceDefinition, config_file: str | Path) -> None
```

Members:

- `def load() -> T_Settings` — Validate and publish the selected service's process settings.
- `def check_config() -> T_Settings` — Validate the complete YAML without writing or binding App settings.
- `def read_config() -> dict[str, Any]` — Read the selected round-trip YAML without changing it.
- `def write_config(data: Mapping[str, Any]) -> None` — Validate and explicitly replace the selected YAML contents.
- `def init_config() -> None` — Create a missing service YAML with the complete applicable defaults.
- `def sync_config() -> None` — Add missing defaults while preserving operator values and comments.
- `property diagnostics: tuple[str, ...]` — Return non-fatal advice from the last successful validation.
- `def inspect_diagnostics(data: Mapping[str, Any]) -> tuple[str, ...]` — Report keys the settings do not declare, at every level, and service/App usage warnings.

## Module `oldman.conf.containers`

Import with `from oldman.conf.containers import <name>`.

### `AsyncConfigDict`

class · defined in `oldman.conf.containers`

```python
class AsyncConfigDict
```

轻量级异步配置缓存。已废弃：改用 YamlStore，值由 MsgspecModel schema 声明。

Constructor:

```python
AsyncConfigDict(config_path: str | Path, check_interval: float=5.0, auto_reload: bool=True)
```

Members:

- `def get_empty_data() -> dict[str, Any]` — 获取一个空的数据结构
- `def on_file_changed(old_data: dict, new_data: dict) -> None` — 子类重写此方法来感知数据变化并更新内部缓存
- `async def get_data(force_check: bool=False) -> dict[str, Any]` — 获取配置数据
- `def get_data_sync() -> dict[str, Any]` — 同步获取数据(不检查更新)
- `async def save_data(data: dict[str, Any]) -> None` — 保存数据

### `RedisSet`

class · defined in `oldman.conf.containers`

```python
class RedisSet
```

Redis 原生集合 ``<服务命名空间>:store:<name>``，成员是 str 或 int。

Constructor:

```python
RedisSet(member_type: type[E], name: str, *, client: BinaryRedisClient | None=None) -> None
```

Members:

- `property key: str` — The Redis key; building it needs the service settings.
- `async def add(member: E) -> bool` — Add one member; True when the set did not have it.
- `async def remove(member: E) -> bool` — Remove one member; True when the set had it.
- `async def contains(member: E) -> bool` — Whether the set has this member.
- `async def members() -> set[E]` — Every member. Reads the whole set: for a membership check use contains().
- `async def random() -> E | None` — One member picked at random, or None when the set is empty.

### `RedisSettings`

class · defined in `oldman.conf.containers`

```python
class RedisSettings
```

Store typed dynamic settings in Redis-native data structures.

Constructor:

```python
RedisSettings(client: RedisSettingsClient | None=None, namespace: str | None=None) -> None
```

Members:

- `property namespace: str` — The key prefix: the one given, or ``<service namespace>:settings``.
- `async def get_value(key: str, default: Any=None) -> SettingsValue | Any` — Return one decoded value or default only when the key is absent.
- `async def set_value(key: str, value: SettingsValue, ttl: int | None=None) -> None` — Encode and store one value with an optional expiry in seconds.
- `async def delete(key: str) -> bool` — Delete any settings data structure stored at key.
- `async def add_set_member(key: str, value: SettingsValue) -> bool` — Add one typed member and report whether the set changed.
- `async def remove_set_member(key: str, value: SettingsValue) -> bool` — Remove one typed member and report whether the set changed.
- `async def get_set_members(key: str) -> set[SettingsValue]` — Return every decoded member from a settings set.
- `async def contains_set_member(key: str, value: SettingsValue) -> bool` — Return whether a typed member exists in a settings set.
- `async def get_random_set_member(key: str) -> SettingsValue | None` — Return one decoded random member or None for an empty set.
- `async def append_list_item(key: str, value: SettingsValue) -> int` — Append one typed item to the right side of a settings list.
- `async def prepend_list_item(key: str, value: SettingsValue) -> int` — Prepend one typed item to the left side of a settings list.
- `async def pop_first_list_item(key: str) -> SettingsValue | None` — Remove and decode the first settings-list item.
- `async def pop_last_list_item(key: str) -> SettingsValue | None` — Remove and decode the last settings-list item.
- `async def get_list_items(key: str, start: int=0, stop: int=-1) -> list[SettingsValue]` — Return an inclusive decoded range from a settings list.

### `RedisStore`

class · defined in `oldman.conf.containers`

```python
class RedisStore(TypedStore[T])
```

存在一个 Redis 键里的类型化配置：``<服务命名空间>:store:<name>``，值是整个 schema 的 msgpack。

Constructor:

```python
RedisStore(schema: type[T], name: str, *, client: BinaryRedisClient | None=None) -> None
```

Members:

- `property key: str` — The Redis key; building it needs the service settings.
- `async def get() -> T` — 当前值。每次都是新解码的对象，改了再 save 即可。

### `YamlStore`

class · defined in `oldman.conf.containers`

```python
class YamlStore(TypedStore[T])
```

存在一个 YAML 文件里的类型化配置。

Constructor:

```python
YamlStore(schema: type[T], config_path: str | Path, *, check_interval: float=5.0) -> None
```

Members:

- `async def get() -> T` — 当前值。它是共享对象：改了就 save；只想临时换个值用，先复制一份（msgspec.structs.replace）。
- `def on_file_changed(old: T, new: T) -> None` — 文件被外部修改（包括删除）并重新加载之后调用；子类在这里重置由配置派生的状态。

## Module `oldman.conf.manager`

Service-scoped YAML settings loading and management.

Import with `from oldman.conf.manager import <name>`.

### `apply_schema_descriptions`

function · defined in `oldman.conf.manager`

```python
def apply_schema_descriptions(data: Mapping[str, Any], model_class: type[BaseModel], *, indent: int=0) -> CommentedMap
```

Put each field's description one line above its key, exactly once, keeping every other comment.

### `deep_merge_missing`

function · defined in `oldman.conf.manager`

```python
def deep_merge_missing(existing: dict[str, Any], defaults: dict[str, Any], *, model_class: type[BaseModel] | None=None) -> dict[str, Any]
```

Add missing values with optional schema-aware recursion.

### `direct_model_class`

function · defined in `oldman.conf.manager`

```python
def direct_model_class(annotation: Any) -> type[BaseModel] | None
```

Return a directly nested Pydantic model class.

### `sync_model_mapping`

function · defined in `oldman.conf.manager`

```python
def sync_model_mapping(existing: Mapping[str, Any], defaults: Mapping[str, Any], model_class: type[BaseModel]) -> dict[str, Any]
```

Add missing schema fields without replacing operator values or aliases.

### `unknown_settings_keys`

function · defined in `oldman.conf.manager`

```python
def unknown_settings_keys(data: Mapping[str, Any], model_class: type[BaseModel], prefix: str='') -> list[str]
```

Report unknown keys while respecting Pydantic field aliases.

## Module `oldman.conf.schemas`

Settings schemas for Oldman applications.

Import with `from oldman.conf.schemas import <name>`.

### `AccountConfig`

class · defined in `oldman.conf.schemas`

```python
class AccountConfig(ConfigModel)
```

Where the site's own account pages live; the built-in Admin keeps its pages under its own prefix.

Members:

- `login_url: str = Field(default='/login', description='Login page and its submit; requests that need a signed-in user…`
- `classmethod def validate_login_url(value: str) -> str` — Registered as a route and redirected to, so a plain local path.

### `APIKeyConfig`

class · defined in `oldman.conf.schemas`

```python
class APIKeyConfig(ConfigModel)
```

One named key the api_key method accepts from callers that are not users: other services, scripts.

Members:

- `secret: str = Field(repr=False, description='The key itself; a caller sends it in the X-API-Key header')`
- `query_param: str | None = Field(default=None, description='Also read the key from this query parameter; access logs, browser …`
- `authorization: bool = Field(default=False, description='Also accept the key as Authorization: Bearer <key>')`
- `classmethod def validate_secret(value: object) -> str` — An empty key would let every caller that sends nothing match it.
- `classmethod def validate_query_param(value: object) -> str | None` — Blank means header only.

### `AuthConfig`

class · defined in `oldman.conf.schemas`

```python
class AuthConfig(ConfigModel)
```

How a Web service recognizes who, or what, is making each request.

Members:

- `authenticators: list[str] | None = Field(default=None, description='Request authentication methods tried in order, first match wins: b…`
- `login_backends: list[str] = Field(default_factory=lambda: ['users'], description='Credential checks tried in order at sign-in a…`
- `jwt: JWTConfig = Field(default_factory=JWTConfig, description='Bearer access token settings')`
- `api_keys: dict[str, APIKeyConfig] = Field(default_factory=dict, description='Keys the api_key method accepts, by name; the name is requ…`
- `http_basic: HTTPBasicConfig = Field(default_factory=HTTPBasicConfig, description='Accounts the http_basic method accepts')`
- `ip_allowlist: dict[str, list[str]] = Field(default_factory=dict, description='Networks the ip_allowlist method accepts, by name; the nam…`
- `classmethod def validate_ip_allowlist(value: dict[str, list[str]]) -> dict[str, list[str]]` — Each entry lists addresses or CIDR blocks; a block with host bits set is refused rather than widened.
- `def validate_distinct_api_keys() -> AuthConfig` — Two names on one key would leave it unclear which caller is calling.

### `CoreConfig`

class · defined in `oldman.conf.schemas`

```python
class CoreConfig(ConfigModel)
```

Core application config.

Members:

- `app_name: str = Field(default='oldman', description='Application name')`
- `namespace: str | None = Field(default=None, description='Prefix of every Redis key and channel this service uses. Services …`
- `data_dir: Path = Field(default=PROJECT_ROOT / 'data', description='Application data directory')`
- `time_zone: str = Field(default='Asia/Singapore', description='Application time zone')`
- `id_alphabet: str | None = Field(default=None, description='Alphabet that encodes public ids (oldman.utils.hash_ids). Settings…`
- `debug: bool = Field(default=False, description='Debug mode for every service: Sanic debug and error details, DEBU…`
- `classmethod def validate_id_alphabet(value: object) -> str | None` — Blank means not generated yet; a set alphabet must be one Sqids accepts.
- `classmethod def validate_namespace(value: object) -> str | None` — The namespace is the first segment of every key, so it may not contain the separator.
- `def validate_namespace_fallback() -> CoreConfig` — Unset, the namespace is app_name, which then has to be one as well.

### `CSRFConfig`

class · defined in `oldman.conf.schemas`

```python
class CSRFConfig(ConfigModel)
```

Stateless Web CSRF policy.

Members:

- `ttl: int = Field(default=3600, gt=0, description='CSRF token lifetime in seconds')`
- `check_referer: bool = Field(default=True, description='Enforce same-origin on unsafe requests via Origin (then Referer); …`
- `check_url: bool = Field(default=False, description='Bind each CSRF token to its request path')`
- `enforce: bool = Field(default=False, description='Validate every unsafe-method request, exempting handlers marked c…`
- `cookie_name: str = Field(default='csrf_id', min_length=1, description="Cookie holding an anonymous visitor's random id…`

### `DatabaseConfig`

class · defined in `oldman.conf.schemas`

```python
class DatabaseConfig(ConfigModel)
```

Database config.

Members:

- `url: OptionalSecret = Field(default=None, description='SQLAlchemy async database URL, which routinely carries a password')`
- `echo: bool | None = Field(default=None, description='Override SQLAlchemy engine echo; null follows core.debug')`
- `enable_sql_logging: bool = Field(default=False, description='Enable SQL query tracking and performance summaries')`
- `cache_pool_size: int = Field(default=5, gt=0, description="Connections in the model cache's own pool, opened on the first …`
- `cache_pool_timeout: float = Field(default=1.0, gt=0, description="Seconds a model cache miss waits for a cache pool connection …`

### `FingerprintRateLimitConfig`

class · defined in `oldman.conf.schemas`

```python
class FingerprintRateLimitConfig(ConfigModel)
```

One browser-fingerprint and IP rate-limit rule.

Members:

- `window: int = Field(default=60, gt=0, description='Rate-limit window in seconds')`
- `fp_max: int = Field(default=20, gt=0, description='Maximum requests per fingerprint and window')`
- `ip_max: int = Field(default=40, gt=0, description='Maximum requests per IP and window')`

### `FingerprintSecurityConfig`

class · defined in `oldman.conf.schemas`

```python
class FingerprintSecurityConfig(ConfigModel)
```

Browser fingerprint encryption and anomaly policy.

Members:

- `enabled: bool = Field(default=False, description='Enable browser fingerprint checks; routes still opt in individual…`
- `aes_secret_key: OptionalSecret = Field(default=None, description='Base64-encoded 32-byte key shared with the browser')`
- `timestamp_max_diff: int = Field(default=300 * 1000, gt=0, description='Maximum accepted browser timestamp difference in milli…`
- `rate_limits: dict[str, FingerprintRateLimitConfig] = Field(default_factory=_default_fingerprint_rate_limits, description='Endpoint-specific fingerprint …`
- `max_fingerprints_per_ip: int = Field(default=5, gt=0, description='Maximum fingerprints associated with one IP')`
- `max_ips_per_fingerprint: int = Field(default=3, gt=0, description='Maximum IPs associated with one fingerprint')`
- `blacklist_threshold: int = Field(default=5, gt=0, description='Violations required before automatic blocking')`
- `blacklist_duration: int = Field(default=3600, gt=0, description='Automatic blacklist duration in seconds')`
- `violation_ttl: int = Field(default=3600, gt=0, description='Violation counter lifetime in seconds')`
- `classmethod def validate_aes_secret_key(value: object) -> str | None` — Allow settings tools to fill blanks and validate configured AES-256 keys.
- `def validate_default_rate_limit() -> FingerprintSecurityConfig` — Require the fallback rule consumed by every unspecified endpoint.

### `FrontendConfig`

class · defined in `oldman.conf.schemas`

```python
class FrontendConfig(ConfigModel)
```

Frontend build and dev-server config.

Members:

- `vite_dev_server_url: str = Field(default='http://localhost:5173', description='Vite development server URL')`

### `HTTPBasicConfig`

class · defined in `oldman.conf.schemas`

```python
class HTTPBasicConfig(ConfigModel)
```

Fixed accounts the http_basic method accepts: tools and machines that speak HTTP Basic.

Members:

- `realm: str = Field(default='oldman', description="Named by the browser's sign-in prompt; sent in WWW-Authenticat…`
- `accounts: dict[str, str] = Field(default_factory=dict, repr=False, description='Username to password, as written; the settings…`
- `classmethod def validate_realm(value: str) -> str` — The realm is sent inside a quoted header value; a quote or control character would break out of it.
- `classmethod def validate_accounts(value: dict[str, str]) -> dict[str, str]` — HTTP Basic splits the credential at the first colon, so a username cannot hold one.

### `HttpClientConfig`

class · defined in `oldman.conf.schemas`

```python
class HttpClientConfig(ConfigModel)
```

HTTP client config.

Members:

- `max_connections: int = Field(default=300, description='Maximum HTTP connection pool size')`
- `user_agent: str = Field(default='okhttp/3.8.7', description='Default outbound HTTP user agent')`

### `I18nConfig`

class · defined in `oldman.conf.schemas`

```python
class I18nConfig(ConfigModel)
```

Internationalization config.

Members:

- `use_i18n: bool = Field(default=False, description='Enable internationalization')`
- `use_i18n_path: bool = Field(default=False, description='Enable language-prefixed routes')`
- `default_language: str = Field(default='en', description='Default language code')`
- `languages: dict[str, I18nLanguageConfig] = Field(default_factory=_default_i18n_languages, description='Canonical project language definitions')`
- `preference_url: str = Field(default='/preferences/language', description="Endpoint the browser posts a visitor's language…`
- `classmethod def validate_preference_url(value: str) -> str` — The browser posts here from any page, signed in or not.
- `classmethod def normalize_language_keys(value: object) -> object` — Normalize configured canonical codes before building child models.
- `classmethod def normalize_default_language(value: object) -> str` — Require one standard language tag before resolving project aliases.
- `def serialize_language_overrides(languages: dict[str, I18nLanguageConfig]) -> dict[str, dict[str, object]]` — Preserve compact user overrides instead of materializing runtime defaults.
- `def validate_language_contract() -> I18nConfig` — Resolve the default language and reject ambiguous project aliases.

### `I18nLanguageConfig`

class · defined in `oldman.conf.schemas`

```python
class I18nLanguageConfig(ConfigModel)
```

Optional user overrides for one canonical language definition.

Members:

- `aliases: list[str] = Field(default_factory=list, description='Accepted BCP 47 language aliases')`
- `name: str = Field(default='', description='Language menu display name override')`
- `flag: str = Field(default='', description='Language menu flag asset override')`
- `classmethod def normalize_aliases(value: list[str]) -> list[str]` — Validate and canonicalize explicitly configured aliases.
- `classmethod def validate_name(value: str) -> str` — Reject an explicitly blank display name.

### `JWTConfig`

class · defined in `oldman.conf.schemas`

```python
class JWTConfig(ConfigModel)
```

Bearer access tokens: signed JWTs a client sends in the Authorization header.

Members:

- `secret: OptionalSecret = Field(default=None, description="HMAC key the tokens are signed with, apart from web.security.secre…`
- `access_token_ttl: int = Field(default=900, gt=0, description='Access token lifetime in seconds')`
- `refresh_token_ttl: int = Field(default=60 * 60 * 24 * 7, gt=0, description='Refresh token lifetime in seconds, counted again…`
- `issuer: str | None = Field(default=None, description='Written to the iss claim and required in it when set')`
- `audience: str | None = Field(default=None, description='Written to the aud claim and required in it when set')`
- `classmethod def validate_secret(value: object) -> str | None` — A short HMAC key can be brute-forced offline from any one token.

### `LoggingConfig`

class · defined in `oldman.conf.schemas`

```python
class LoggingConfig(ConfigModel)
```

Logging level, file location and console color configuration.

Members:

- `level: int | None = Field(default=None, description='Logging level; null follows core.debug: DEBUG when it is on, INFO …`
- `dir: Path = Field(default=PROJECT_ROOT / 'logs', description='Log file directory')`
- `color: Literal['auto', 'always', 'never'] = Field(default='auto', description='Console color policy')`
- `rotate_when: Literal['S', 'M', 'H', 'D', 'W0', 'W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'midnight'] | None = Field(default='D', description='Time-based rollover unit; null disables time rotation so that max_b…`
- `rotate_interval: int = Field(default=1, gt=0, description='How many rotate_when units between rollovers')`
- `max_bytes: int = Field(default=0, ge=0, description='Size-based rollover threshold in bytes; only usable when rotate…`
- `backup_count: int = Field(default=3, ge=0, description='How many rotated files to keep')`
- `def validate_rotation() -> LoggingConfig` — Time and size rollover are mutually exclusive, the same rule the handler enforces.
- `def resolved_level(*, debug: bool) -> int` — The level to install: the configured one, or DEBUG / INFO by the debug switch.
- `classmethod def normalize_level(value: object) -> object` — Accept legacy level names while retaining the integer runtime contract.

### `MailConfig`

class · defined in `oldman.conf.schemas`

```python
class MailConfig(ConfigModel)
```

Outgoing mail settings shared by Web and task processes.

Members:

- `backend: str = Field(default='oldman.mail.backends.console.ConsoleEmailBackend', description='Dotted import path o…`
- `default_from_email: str = Field(default='webmaster@localhost', min_length=1, description='Sender used when a message names no…`
- `subject_prefix: str = Field(default='[Oldman] ', description='Prefix put in front of subjects sent through mail_admins()')`
- `admins: list[str] = Field(default_factory=list, description='Recipients of mail_admins()')`
- `file_path: str | None = Field(default=None, description='Directory the filebased backend writes .eml files into')`
- `smtp: SMTPMailConfig = Field(default_factory=SMTPMailConfig, description='SMTP transport settings')`
- `classmethod def validate_backend_path(value: str) -> str` — Backends are imported lazily, so at least the path shape is checked here.

### `MediaConfig`

class · defined in `oldman.conf.schemas`

```python
class MediaConfig(ConfigModel)
```

Media storage and URL config.

Members:

- `storage: str = Field(default='default', description='Named storage used for media files')`
- `url: str = Field(default='/media/', description='Media URL prefix')`

### `MessagesConfig`

class · defined in `oldman.conf.schemas`

```python
class MessagesConfig(ConfigModel)
```

Cookie-backed one-time Web message configuration.

Members:

- `enabled: bool = Field(default=False, description='Install one-time Web messages')`

### `NATSBusConfig`

class · defined in `oldman.conf.schemas`

```python
class NATSBusConfig(ConfigModel)
```

Core event/RPC lifecycle, independent of named transports and Taskiq.

Members:

- `enabled: bool = Field(default=False, description='Enable the process-local event/RPC connection')`
- `nats_alias: str = Field(default='DEFAULT', min_length=1, description='Named NATS connection for events and RPC')`
- `consume: bool = Field(default=False, description='Receive App events in a long-running Web or Simple service')`
- `namespace: str | None = Field(default=None, description='Shared project/environment namespace; required when enabled')`
- `peer_id: str | None = Field(default=None, description='Explicit local identity for directed subscriptions and source head…`
- `serializer_mode: Literal['msgpack', 'msgspec_json'] = Field(default='msgpack', description='Bytes codec agreed by both ends')`
- `startup_timeout: float = Field(default=30, gt=0, allow_inf_nan=False, description='Total seconds allowed to establish the se…`
- `graceful_timeout: float = Field(default=10, gt=0, allow_inf_nan=False, description='Shared normal-completion wait for active …`
- `classmethod def validate_address_name(value: str | None) -> str | None` — Keep explicit identities intact; absent is different from an invalid name.
- `def validate_enabled_namespace() -> NATSBusConfig` — Disabled services may retain receive settings without opening facilities.

### `NATSConfig`

class · defined in `oldman.conf.schemas`

```python
class NATSConfig(ConfigModel, Mapping[str, NATSConnectionConfig])
```

Case-sensitive named NATS connections, matching the Redis mapping convention.

Members:

- `DEFAULT: NATSConnectionConfig = Field(default_factory=lambda: NATSConnectionConfig(nats_url='nats://localhost:4222'), description='…`
- `classmethod def merge_default_connection(value: Any) -> Any` — Retain the built-in URL when only DEFAULT connection options are supplied.
- `def validate_connection_names() -> NATSConfig` — Reject blank aliases without silently normalizing deployment names.

### `NATSConnectionConfig`

class · defined in `oldman.conf.schemas`

```python
class NATSConnectionConfig(ConfigModel)
```

One native NATS connection; validation never reads certificates or connects.

Members:

- `nats_url: Secret = Field(min_length=1, description='NATS URL, optionally containing encoded credentials')`
- `connect_timeout: float = Field(default=2, gt=0, allow_inf_nan=False, description='NATS connection attempt timeout in seconds…`
- `reconnect_time_wait: float = Field(default=2, gt=0, allow_inf_nan=False, description='Delay between native NATS reconnect attemp…`
- `tls_ca_file: Path | None = Field(default=None, description='Trusted NATS server CA file; null uses system trust')`
- `tls_cert_file: Path | None = Field(default=None, description='Optional client certificate for mutual TLS')`
- `tls_key_file: Path | None = Field(default=None, description='Private key paired with the client certificate')`
- `credentials_file: Path | None = Field(default=None, description='NATS .creds identity file, exclusive with URL credentials')`
- `def validate_connection() -> NATSConnectionConfig` — Reject ambiguous endpoints and authentication without exposing secrets.

### `ProcessConfig`

class · defined in `oldman.conf.schemas`

```python
class ProcessConfig(ConfigModel)
```

Process lifecycle config.

Members:

- `pid_dir: Path = Field(default=PROJECT_ROOT / 'pids', description='Service PID file directory')`
- `stop_timeout: float = Field(default=60, gt=0, allow_inf_nan=False, description='Seconds the stop command waits for a Web …`

### `ProxyConfig`

class · defined in `oldman.conf.schemas`

```python
class ProxyConfig(ConfigModel)
```

Media proxy runtime config.

Members:

- `connect_timeout: int = Field(default=5, description='Proxy connection timeout in seconds')`
- `read_timeout: int = Field(default=10, description='Proxy read timeout in seconds')`

### `RedisCacheConfig`

class · defined in `oldman.conf.schemas`

```python
class RedisCacheConfig(ConfigModel)
```

Configuration for the Redis-backed cache implementation.

Members:

- `client: str = Field(default='CACHE', min_length=1, description='Named Redis client used by the cache')`
- `serializer: str = Field(default='pickle', min_length=1, description='Redis cache serializer name')`

### `RedisConfig`

class · defined in `oldman.conf.schemas`

```python
class RedisConfig(ConfigModel, Mapping[str, RedisConnectionConfig])
```

Case-sensitive mapping of named Redis connection configs.

Members:

- `DEFAULT: RedisConnectionConfig = Field(default_factory=lambda: _default_redis_connection('DEFAULT'), description='Default Redis conn…`
- `CACHE: RedisConnectionConfig = Field(default_factory=lambda: _default_redis_connection('CACHE'), description='Redis connection use…`
- `SESSION: RedisConnectionConfig = Field(default_factory=lambda: _default_redis_connection('SESSION'), description='Redis connection u…`
- `classmethod def merge_builtin_connections(value: Any) -> Any` — Merge partial built-in aliases without inventing URLs for custom aliases.
- `def validate_connection_names() -> RedisConfig` — Reject empty custom connection names.

### `RedisConnectionConfig`

class · defined in `oldman.conf.schemas`

```python
class RedisConnectionConfig(ConfigModel)
```

One named Redis connection and its redis-py pool options.

Members:

- `redis_url: Secret = Field(min_length=1, description='Redis connection URL: redis://host:port/db over TCP (default), red…`
- `decode_responses: bool = Field(default=True, description='Decode Redis responses to strings')`
- `max_connections: int = Field(default=1024, gt=0, description='Maximum Redis connection pool size')`
- `health_check_interval: int = Field(default=30, ge=0, description='Redis connection health-check interval')`
- `retry_attempts: int = Field(default=3, ge=0, description='Redis connection retry attempts')`
- `retry_on_timeout: bool = Field(default=True, description='Retry Redis operations that time out')`
- `protocol: int = Field(default=2, ge=2, le=3, description='Redis RESP protocol version')`
- `backoff_base: float = Field(default=0.1, ge=0, description='Redis retry exponential-backoff base')`
- `backoff_cap: float = Field(default=2.0, ge=0, description='Redis retry exponential-backoff cap')`
- `socket_keepalive: bool = Field(default=True, description='Enable TCP keepalive for Redis TCP connections')`
- `socket_keepalive_idle: int = Field(default=60, gt=0, description='TCP keepalive idle time')`
- `socket_keepalive_interval: int = Field(default=10, gt=0, description='TCP keepalive probe interval')`
- `socket_keepalive_count: int = Field(default=3, gt=0, description='TCP keepalive probe count')`
- `classmethod def validate_redis_url(value: str) -> str` — Reject blank Redis URLs while retaining the configured value.
- `def validate_connection_options() -> RedisConnectionConfig` — Allow only prefixed redis-py extensions without duplicate meanings.
- `property connection_options: dict[str, Any]` — Return redis-py extension options without their settings prefix.
- `def client_options(*, decode_responses: bool | None=None) -> dict[str, Any]` — Return constructor options for the concrete async Redis client.

### `SessionConfig`

class · defined in `oldman.conf.schemas`

```python
class SessionConfig(ConfigModel)
```

Optional Redis-backed Web session configuration.

Members:

- `enabled: bool = Field(default=False, description='Install Web session middleware')`
- `redis_alias: str = Field(default='SESSION', min_length=1, description='Named Redis connection used by sessions')`
- `expiry: int = Field(default=60 * 60 * 12, gt=0, description='Session lifetime in seconds for an ordinary login (t…`
- `remember_expiry: int = Field(default=60 * 60 * 24 * 30, gt=0, description="Session lifetime in seconds when the user ticks…`
- `cookie_name: str = Field(default='session_id', min_length=1, description='Browser session cookie name')`
- `cookie_domain: str | None = Field(default=None, description='Optional browser session cookie domain')`
- `cookie_httponly: bool = Field(default=True, description='Hide the session cookie from browser scripts')`
- `cookie_secure: bool = Field(default=False, description='Restrict the session cookie to HTTPS')`
- `cookie_samesite: Literal['Lax', 'Strict', 'None'] | None = Field(default='Lax', description='Browser SameSite policy for the session cookie')`

### `SMTPMailConfig`

class · defined in `oldman.conf.schemas`

```python
class SMTPMailConfig(ConfigModel)
```

Transport settings for the SMTP mail backend.

Members:

- `host: str = Field(default='localhost', min_length=1, description='SMTP server host name or address')`
- `port: int = Field(default=25, ge=1, le=65535, description='SMTP server port')`
- `username: str | None = Field(default=None, description='SMTP login user; None sends without authentication')`
- `password: OptionalSecret = Field(default=None, description='SMTP login password')`
- `use_tls: bool = Field(default=False, description='Upgrade the connection with STARTTLS after connecting (usually po…`
- `use_ssl: bool = Field(default=False, description='Open an implicit TLS connection (usually port 465)')`
- `timeout: float = Field(default=10.0, gt=0, description='Connection and command timeout in seconds')`
- `local_hostname: str | None = Field(default=None, description='Host name announced in EHLO; None uses the local host name')`
- `def validate_tls_mode() -> Self` — STARTTLS and implicit TLS are two different handshakes; pick one.

### `SSEConfig`

class · defined in `oldman.conf.schemas`

```python
class SSEConfig(ConfigModel)
```

Optional distributed browser event configuration.

Members:

- `enabled: bool = Field(default=False, description='Enable Redis-backed distributed SSE delivery')`
- `redis_alias: str = Field(default='SSE', min_length=1, description='Named Redis connection used by SSE')`
- `heartbeat_interval: float = Field(default=15.0, gt=0, description='Idle heartbeat interval in seconds')`
- `session_check_interval: float = Field(default=30.0, gt=0, description='Authenticated session validation interval in seconds')`
- `queue_size: int = Field(default=100, gt=0, description='Default bounded SSE connection queue size')`
- `max_message_size: int = Field(default=65536, gt=0, description='Maximum encoded Redis event size in bytes')`

### `StaticConfig`

class · defined in `oldman.conf.schemas`

```python
class StaticConfig(ConfigModel)
```

Static assets config.

Members:

- `dir: Path = Field(default=PROJECT_ROOT / 'static', description='Static source directory')`
- `root: str = Field(default=str(PROJECT_ROOT / 'static'), description='Static file root')`
- `url: str = Field(default='/static/', description='Static URL prefix')`

### `StorageBackendConfig`

class · defined in `oldman.conf.schemas`

```python
class StorageBackendConfig(ConfigModel)
```

One importable storage backend and its backend-specific options.

Members:

- `backend: str = Field(description='Dotted import path of the storage backend')`
- `options: dict[str, Any] = Field(default_factory=dict, description='Storage backend options')`
- `classmethod def validate_backend_path(value: str) -> str` — Strip and validate a module attribute import path.

### `StoragesConfig`

class · defined in `oldman.conf.schemas`

```python
class StoragesConfig(ConfigModel, Mapping[str, StorageBackendConfig])
```

Mapping of the default storage and dynamically named storage aliases.

Members:

- `default: StorageBackendConfig = Field(default_factory=_default_storage_backend, description='Default file storage backend')`
- `def validate_storage_aliases() -> StoragesConfig` — Reject blank aliases and the reserved in-memory backend alias.

### `TaskiqConfig`

class · defined in `oldman.conf.schemas`

```python
class TaskiqConfig(ConfigModel)
```

Distributed task limits, separate from fixed local Worker configuration.

Members:

- `enabled: bool = Field(default=False, description='Explicitly enable Taskiq for this service')`
- `namespace: str | None = Field(default=None, description='Shared task namespace; required when enabled')`
- `nats_alias: str = Field(default='DEFAULT', min_length=1, description='Named NATS connection for task transport')`
- `redis_alias: str = Field(default='DEFAULT', min_length=1, description='Named Redis connection for results and schedule…`
- `consume_queues: list[str] = Field(default_factory=lambda: ['default'], min_length=1, description="Queues sharing this service's…`
- `workers: int = Field(default=2, gt=0, description='Number of task execution processes')`
- `max_async_tasks: int = Field(default=100, gt=0, description='Concurrent tasks per process, shared by all queues')`
- `max_prefetch: int = Field(default=0, ge=0, description='Extra Receiver admission slots beyond max_async_tasks; zero add…`
- `startup_timeout: float = Field(default=30, gt=0, allow_inf_nan=False, description='Total seconds allowed for one initializat…`
- `startup_attempts: int = Field(default=3, gt=0, description='Initial attempts per execution position, including the first')`
- `shutdown_timeout: float = Field(default=5, gt=0, allow_inf_nan=False, description='Resource cleanup budget in seconds, after …`
- `stop_timeout: float = Field(default=60, gt=0, allow_inf_nan=False, description='Total service stop deadline before killin…`
- `ack_wait: float = Field(default=60, gt=0, allow_inf_nan=False, description='Consumer acknowledgement wait; renewal ru…`
- `publish_timeout: float = Field(default=5, gt=0, allow_inf_nan=False, description='One publish confirmation or broadcast flus…`
- `ack_timeout: float = Field(default=5, gt=0, allow_inf_nan=False, description='One acknowledged completion timeout')`
- `duplicate_window: float = Field(default=120, gt=0, allow_inf_nan=False, description='Stream publish-deduplication window in s…`
- `result_ex_time: int = Field(default=86400, gt=0, description='Result retention in seconds from its write, not its last re…`
- `stream_max_bytes: int = Field(default=-1, description='Stream byte limit; -1 uses the server/account capacity')`
- `stream_replicas: Literal[1, 3, 5] = Field(default=1, description='JetStream replicas; the deployment must provide enough nodes')`
- `max_ack_pending: int = Field(default=1000, gt=0, description='Unacknowledged tasks across all consumers of one queue')`
- `schedule_update_interval: int = Field(default=5, gt=0, description='Seconds between native schedule-source refreshes')`
- `classmethod def validate_namespace(value: str | None) -> str | None` — An omitted disabled namespace is valid; supplied names are always checked.
- `classmethod def validate_queues(values: list[str]) -> list[str]` — One subscription per queue; preserve the operator's exact queue names.
- `def validate_limits() -> TaskiqConfig` — Check related values without contacting a task service.

### `TemplateConfig`

class · defined in `oldman.conf.schemas`

```python
class TemplateConfig(ConfigModel)
```

Template config.

Members:

- `dir: Path = Field(default=PROJECT_ROOT / 'templates', description='Server-rendered template directory')`

### `WebConfig`

class · defined in `oldman.conf.schemas`

```python
class WebConfig(ConfigModel)
```

Web server and browser-facing service config.

Members:

- `listen_host: str = Field(default='::', description='Web server listen host')`
- `listen_port: int = Field(default=17998, description='Web server listen port')`
- `auto_reload: bool = Field(default=False, description='Enable source auto reload')`
- `workers: int = Field(default=1, description='Web server worker count')`
- `access_log: bool = Field(default=False, description='Enable HTTP access logging')`
- `response_timeout: int = Field(default=120, description='Sanic response timeout in seconds')`
- `request_timeout: int = Field(default=120, description='Sanic request timeout in seconds')`
- `keep_alive_timeout: int = Field(default=120, description='Sanic keep-alive timeout in seconds')`
- `real_ip_header: str = Field(default='X-Real-IP', description='Header containing the client IP address')`
- `proxies_count: int | None = Field(default=None, description='Number of trusted proxies that append to X-Forwarded-For; unset ig…`
- `forwarded_secret: OptionalSecret = Field(default=None, description='Secret a trusted proxy places in the RFC 7239 Forwarded header; un…`
- `fallback_error_format: Literal['auto', 'html', 'json', 'text'] = Field(default='auto', description='Sanic fallback error response format')`
- `websocket_max_size: int = Field(default=2 ** 20, description='Maximum WebSocket message size in bytes')`
- `websocket_ping_interval: int = Field(default=5, description='WebSocket ping interval in seconds')`
- `websocket_ping_timeout: int = Field(default=20, description='WebSocket ping timeout in seconds')`
- `domain: str = Field(default='http://localhost:17998', description='Public application domain')`
- `security: WebSecurityConfig = Field(default_factory=WebSecurityConfig, description='Web security settings')`
- `session: SessionConfig = Field(default_factory=SessionConfig, description='Web session settings')`
- `auth: AuthConfig = Field(default_factory=AuthConfig, description='Request authentication settings')`
- `account: AccountConfig = Field(default_factory=AccountConfig, description="Addresses of the site's account pages")`
- `messages: MessagesConfig = Field(default_factory=MessagesConfig, description='One-time Web message settings')`
- `sse: SSEConfig = Field(default_factory=SSEConfig, description='Server-sent event settings')`
- `template: TemplateConfig = Field(default_factory=TemplateConfig, description='Template settings')`
- `static: StaticConfig = Field(default_factory=StaticConfig, description='Static asset settings')`
- `media: MediaConfig = Field(default_factory=MediaConfig, description='Media asset settings')`
- `frontend: FrontendConfig = Field(default_factory=FrontendConfig, description='Frontend build settings')`

### `WebSecurityConfig`

class · defined in `oldman.conf.schemas`

```python
class WebSecurityConfig(ConfigModel)
```

Central Web signing, CSRF, and browser-fingerprint settings.

Members:

- `secret_key: OptionalSecret = Field(default=None, description='Server-only root key for purpose-separated Web secrets')`
- `csrf: CSRFConfig = Field(default_factory=CSRFConfig, description='Stateless CSRF policy')`
- `fingerprint: FingerprintSecurityConfig = Field(default_factory=FingerprintSecurityConfig, description='Browser fingerprint security policy')`
- `classmethod def validate_secret_key(value: object) -> str | None` — Allow settings tools to fill blanks and reject weak configured roots.
