# `oldman.web.security`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Web-facing fingerprint security helpers.

Import with `from oldman.web.security import <name>`.

## `AESGcmDecrypt`

class · defined in `oldman.web.security.decryptors`

```python
class AESGcmDecrypt
```

解密前端 Web Crypto API 加密的数据。

Members:

- `staticmethod def decrypt(encrypted_b64: str, aes_secret_key: str) -> tuple[bool, str, dict]` — Decode the browser envelope and return its JSON body.

## `configured_web_security_key`

function · defined in `oldman.web.security.keys`

```python
def configured_web_security_key(purpose: WebSecurityPurpose) -> str
```

Derive one key from the process-wide typed Web settings.

## `derive_web_security_key`

function · defined in `oldman.web.security.keys`

```python
def derive_web_security_key(root_secret: str, purpose: WebSecurityPurpose) -> str
```

Derive one URL-safe key without exposing the configured root.

## `FakeLog`

class · defined in `oldman.web.security.fingerprint`

```python
class FakeLog(MsgspecModel)
```

Members:

- `reason: str`
- `timestamp: int`

## `FINGERPRINT_HEADER`

value · defined in `oldman.web.security.guard`

```python
FINGERPRINT_HEADER = 'X-Oldman-Fingerprint'
```

Header the browser module sends its encrypted `{vid, ts}` payload in.

## `fingerprint_required`

value · defined in `oldman.web.security.guard`

```python
fingerprint_required = method_adaptor(_fingerprint_required)
```

## `get_fingerprint_from_front`

function · defined in `oldman.web.security.fingerprint`

```python
def get_fingerprint_from_front(encrypted_b64: str, aes_secret_key: str, max_diff: int) -> tuple[str, str]
```

从解密后的数据中提取指纹

## `get_stats`

function · defined in `oldman.web.security.fingerprint`

```python
async def get_stats(fingerprint: str)
```

管理接口 - 查看指纹统计

## `log_fake_fingerprint_attempt`

function · defined in `oldman.web.security.fingerprint`

```python
async def log_fake_fingerprint_attempt(ip: str, reason: str)
```

记录伪造指纹尝试

## `validate_payload`

function · defined in `oldman.web.security.fingerprint`

```python
def validate_payload(payload: dict, max_diff: int) -> tuple[bool, str, str]
```

验证解密后的数据

## `WebSecurityPurpose`

class · defined in `oldman.web.security.keys`

```python
class WebSecurityPurpose(StrEnum)
```

Protocols that must not reuse one another's signing key.

## Module `oldman.web.security.store`

The Redis connection that holds Web security state.

Import with `from oldman.web.security.store import <name>`.

### `security_redis_alias`

function · defined in `oldman.web.security.store`

```python
def security_redis_alias() -> str
```

Name the Redis connection that every Web security subsystem must share.

### `security_redis_connection`

function · defined in `oldman.web.security.store`

```python
async def security_redis_connection() -> Any
```

Open the decoded connection holding Web security state.
