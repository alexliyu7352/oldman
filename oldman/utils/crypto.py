"""Cryptographic primitives: block padding, AES helpers, PBKDF2 and token generation.

This module owns algorithms only. Policy - which algorithm a subsystem uses, how its
output is stored, when it is upgraded - belongs to that subsystem: password records are
formatted by `oldman.auth.security`, proxy URL sealing by `oldman.contrib.proxy`.
Nothing here reads settings or decides a key; every function takes what it needs.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import string

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def pad_pkcs7(data: bytes, block_size: int = 128) -> bytes:
    """
    使用PKCS7进行数据填充
    128 bits = 16 bytes
    :param data:
    :param block_size:
    :return:
    """
    padder = padding.PKCS7(block_size).padder()  # 128 bits = 16 bytes
    return padder.update(data) + padder.finalize()


def unpad_pkcs7(data: bytes, block_size: int = 128) -> bytes:
    unpadder = padding.PKCS7(block_size).unpadder()
    return unpadder.update(data) + unpadder.finalize()


def aes_encrypt_cbc_pkcs7(key_bytes: bytes, iv_bytes: bytes, plaintext: bytes) -> bytes:
    """
    使用 cryptography 实现 AES-CBC + PKCS7 填充加密
    """
    # PKCS7 填充，block size 为 128 bit（16 字节）
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(plaintext) + padder.finalize()

    cipher = Cipher(
        algorithms.AES(key_bytes),
        modes.CBC(iv_bytes),
        backend=default_backend(),
    )
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    return ciphertext


def aes_decrypt_cbc_pkcs7(key_bytes: bytes, iv_bytes: bytes, ciphertext: bytes) -> bytes:
    """
    使用 cryptography 实现 AES-CBC + PKCS7 填充解密
    """
    cipher = Cipher(
        algorithms.AES(key_bytes),
        modes.CBC(iv_bytes),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()
    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
    return plaintext


AES_GCM_IV_BYTES = 12
AES_GCM_TAG_BYTES = 16


def aes_gcm_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt with AES-GCM, returning `IV || ciphertext || tag`.

    That layout is what the Web Crypto API produces and what `aes_gcm_decrypt` expects,
    so a payload made here can be read there and vice versa.

    `key` is 16, 24 or 32 raw bytes (AES-128/192/256). A fresh random IV is generated for
    every call — reusing one with the same key destroys GCM's security entirely.
    """
    iv = os.urandom(AES_GCM_IV_BYTES)
    return iv + AESGCM(key).encrypt(iv, plaintext, None)


def aes_gcm_decrypt(payload: bytes, key: bytes) -> tuple[bool, str, bytes]:
    """Decrypt `IV || ciphertext || tag`, saying why it failed rather than just that it did.

    Returns `(ok, reason, plaintext)`. The reason matters: a caller has to be able to tell
    "this was not encrypted with our key" from "this arrived truncated", because the two
    mean different things about who sent it. The previous version of this function
    returned an empty string for every failure, which also made a successful decryption of
    an empty plaintext indistinguishable from an error.
    """
    if len(payload) < AES_GCM_IV_BYTES + AES_GCM_TAG_BYTES:
        return False, "data_too_short", b""
    iv, ciphertext_with_tag = payload[:AES_GCM_IV_BYTES], payload[AES_GCM_IV_BYTES:]
    try:
        return True, "success", AESGCM(key).decrypt(iv, ciphertext_with_tag, None)
    except Exception as error:
        # InvalidTag stringifies to "", which would leave a message ending in a colon.
        message = str(error) or type(error).__name__
        if "tag" in message.lower() or "authentication" in message.lower():
            return False, f"authentication_failed:{message}", b""
        return False, f"decryption_error:{message}", b""


def pbkdf2_sha256(raw_password: str, salt: str, iterations: int) -> str:
    """Derive one PBKDF2-HMAC-SHA256 hexadecimal digest.

    The caller owns the iteration count and the record format; this is the algorithm only.
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        raw_password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two digests without leaking where they first differ."""
    return hmac.compare_digest(left, right)


def generate_token(length=10):
    while True:
        token = base64.b32encode(secrets.token_bytes(length)).decode("utf-8").rstrip("=")[:10]
        # 修正易混淆字符替换
        for c in ["I", "L", "O", "1", "0"]:
            token = token.replace(c, "")
        if len(token) < 8:  # 长度不够重来
            continue
        return token


def generate_secure_token(length: int = 10) -> str:
    """Generate a token of exactly `length` characters, drawn from a look-alike-free alphabet.

    I, L, O, 0 and 1 are excluded so that a token can be read aloud or retyped without
    ambiguity. Characters are chosen one at a time with `secrets.choice`, so the length is
    exact by construction.

    The previous implementation encoded random bytes, truncated to ten characters, then
    filtered — which made `length` control neither the output length (always at most ten)
    nor the retry threshold consistently. `generate_secure_token(20)` demanded eighteen
    characters from a ten-character string and looped forever.
    """
    if length < 1:
        raise ValueError("length must be at least 1")
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(length))


_TOKEN_ALPHABET = tuple(c for c in string.ascii_uppercase + string.digits if c not in {"I", "L", "O", "0", "1"})

SEAL_TAG_BYTES = 8


class UrlSealer:
    """Turn bytes into one URL-safe token and back again with the same key.

    Deterministic on purpose: the same input always produces the same token, so callers
    keep their caches and downstream HTTP caches keep working. Each token carries a tag
    derived from its own plaintext, which does two jobs at once - it seeds that token's
    keystream, so no two inputs ever share one, and it rejects a token that was edited
    or forged. Both matter for a value the server will later act on.

    The token grows by a constant 11 characters regardless of input length: 8 tag bytes
    through base64url. The caller owns the key; see `oldman.web.security.keys` for the
    purpose-separated derivation.
    """

    __slots__ = ("_stream_seed", "_tag_proto")

    def __init__(self, key: bytes) -> None:
        """Bind one key; the HMAC prototype is reused so each call only copies its state."""
        if len(key) < 16:
            raise ValueError("UrlSealer key must be at least 16 bytes")
        self._tag_proto = hmac.new(key, digestmod=hashlib.sha256)
        self._stream_seed = hmac.new(key, b"oldman.url-sealer.stream.v1", hashlib.sha256).digest()

    def seal(self, data: bytes) -> str:
        """Return the URL-safe token for `data`."""
        tag = self._tag(data)
        return base64.urlsafe_b64encode(tag + self._mask(data, tag)).decode("ascii").rstrip("=")

    def unseal(self, token: str) -> bytes | None:
        """Return the sealed bytes, or None when the token was edited, forged or malformed."""
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        except (binascii.Error, ValueError):
            return None
        if len(raw) < SEAL_TAG_BYTES:
            return None
        tag, sealed = raw[:SEAL_TAG_BYTES], raw[SEAL_TAG_BYTES:]
        data = self._mask(sealed, tag)
        if not hmac.compare_digest(self._tag(data), tag):
            return None
        return data

    def _tag(self, data: bytes) -> bytes:
        mac = self._tag_proto.copy()
        mac.update(data)
        return mac.digest()[:SEAL_TAG_BYTES]

    def _mask(self, data: bytes, tag: bytes) -> bytes:
        """XOR against a keystream that only this tag can produce."""
        if not data:
            return b""
        # SHAKE gives the whole keystream in one call; chaining SHA-256 blocks instead
        # costs several times more and grows quadratically with the input.
        stream = hashlib.shake_256(self._stream_seed + tag).digest(len(data))
        return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


__all__ = [
    "SEAL_TAG_BYTES",
    "UrlSealer",
    "aes_decrypt_cbc_pkcs7",
    "aes_encrypt_cbc_pkcs7",
    "aes_gcm_decrypt",
    "aes_gcm_encrypt",
    "constant_time_equals",
    "generate_secure_token",
    "generate_token",
    "pad_pkcs7",
    "pbkdf2_sha256",
    "unpad_pkcs7",
]
