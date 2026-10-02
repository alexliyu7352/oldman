# `oldman.utils`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

The package itself exports nothing; import from the modules below.

## Module `oldman.utils.crypto`

Cryptographic primitives: block padding, AES helpers, PBKDF2 and token generation.

Import with `from oldman.utils.crypto import <name>`.

### `aes_decrypt_cbc_pkcs7`

function · defined in `oldman.utils.crypto`

```python
def aes_decrypt_cbc_pkcs7(key_bytes: bytes, iv_bytes: bytes, ciphertext: bytes) -> bytes
```

AES-CBC + PKCS7 解密，只为与已有协议互通；填充不合法时抛 ValueError。

### `aes_encrypt_cbc_pkcs7`

function · defined in `oldman.utils.crypto`

```python
def aes_encrypt_cbc_pkcs7(key_bytes: bytes, iv_bytes: bytes, plaintext: bytes) -> bytes
```

AES-CBC + PKCS7 加密，只为与已有协议互通。

### `aes_gcm_decrypt`

function · defined in `oldman.utils.crypto`

```python
def aes_gcm_decrypt(payload: bytes, key: bytes) -> tuple[bool, str, bytes]
```

Decrypt `IV || ciphertext || tag`, saying why it failed rather than just that it did.

### `aes_gcm_encrypt`

function · defined in `oldman.utils.crypto`

```python
def aes_gcm_encrypt(plaintext: bytes, key: bytes) -> bytes
```

Encrypt with AES-GCM, returning `IV || ciphertext || tag`.

### `constant_time_equals`

function · defined in `oldman.utils.crypto`

```python
def constant_time_equals(left: str | bytes, right: str | bytes) -> bool
```

Compare two secrets or digests without leaking where they first differ.

### `generate_secure_token`

function · defined in `oldman.utils.crypto`

```python
def generate_secure_token(length: int=10) -> str
```

Generate a token of exactly `length` characters, drawn from a look-alike-free alphabet.

### `pad_pkcs7`

function · defined in `oldman.utils.crypto`

```python
def pad_pkcs7(data: bytes, block_size: int=128) -> bytes
```

PKCS7 填充到 block_size 的整数倍。block_size 的单位是**比特**（cryptography 的约定），AES 为 128。

### `pbkdf2_sha256`

function · defined in `oldman.utils.crypto`

```python
def pbkdf2_sha256(raw_password: str, salt: str, iterations: int) -> str
```

Derive one PBKDF2-HMAC-SHA256 hexadecimal digest.

### `SEAL_TAG_BYTES`

value · defined in `oldman.utils.crypto`

```python
SEAL_TAG_BYTES = 8
```

### `unpad_pkcs7`

function · defined in `oldman.utils.crypto`

```python
def unpad_pkcs7(data: bytes, block_size: int=128) -> bytes
```

去掉 PKCS7 填充；填充不合法时抛 ValueError。block_size 的单位是比特，AES 为 128。

### `UrlSealer`

class · defined in `oldman.utils.crypto`

```python
class UrlSealer
```

Turn bytes into one URL-safe token and back again with the same key.

Constructor:

```python
UrlSealer(key: bytes) -> None
```

Members:

- `def seal(data: bytes) -> str` — Return the URL-safe token for `data`.
- `def unseal(token: str) -> bytes | None` — Return the sealed bytes, or None when the token was edited, forged or malformed.

## Module `oldman.utils.date`

Import with `from oldman.utils.date import <name>`.

### `naive_utcnow`

function · defined in `oldman.utils.date`

```python
def naive_utcnow() -> datetime
```

当前 UTC 时间，去掉 tzinfo。

## Module `oldman.utils.module_loading`

Load objects that settings name by dotted import path.

Import with `from oldman.utils.module_loading import <name>`.

### `build_configured`

function · defined in `oldman.utils.module_loading`

```python
def build_configured(names: Sequence[str], builtins: Mapping[str, Callable[[], Any]], *, setting: str) -> list[Any]
```

Build, in order, the objects a settings list names.

### `import_string`

function · defined in `oldman.utils.module_loading`

```python
def import_string(dotted_path: str) -> Any
```

Import the attribute a ``module.attribute`` path names.
