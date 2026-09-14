import base64
import hashlib
import os
import random
import secrets
import string

from async_lru import alru_cache
from Cryptodome.Cipher import AES, ARC4
from Cryptodome.Util.Padding import pad, unpad
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

M3U8_TOKEN_EXPIRE_TIME = 3600 * 24 * 7
MU38_TOKEN_AES_KEY = b"435d73f7-1b6b-4189-a715-c2ab5d19"
MU38_TOKEN_AES_IV = b"3f4165@f1e%13!71"


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


def hash_password(salt, password):
    salted = password + salt
    return hashlib.sha512(salted.encode("utf8")).hexdigest()


def make_salt():
    return hashlib.sha512(str(random.random()).encode("utf8")).hexdigest()


@alru_cache(maxsize=4096)
async def encrypt_m3u8_token(user_id: int, channel_id: str, expire_time: int):
    """
    生成m3u8的token, 使用AES加密
    :param user_id:
    :param channel_id:
    :param expire_time:
    :return:
    """
    if type(user_id) is not int:
        raise TypeError("user_id must be an integer")

    # 生成随机的10个字符
    random_str = "".join(random.sample(string.ascii_letters, 10))
    key = f"{user_id}||{channel_id}||{expire_time}||{random_str}"
    # 进行AES加密
    encrypt = AES.new(MU38_TOKEN_AES_KEY, AES.MODE_CBC, MU38_TOKEN_AES_IV)
    encrypt_content = encrypt.encrypt(pad(key.encode("utf8"), AES.block_size))
    return encrypt_content.hex()


@alru_cache(maxsize=4096)
async def decrypt_m3u8_token(token):
    """
    解密m3u8的token, 使用AES解密
    :param token:
    :return:
    """
    try:
        # 进行AES解密
        decrypt = AES.new(MU38_TOKEN_AES_KEY, AES.MODE_CBC, MU38_TOKEN_AES_IV)
        decrypt_content = decrypt.decrypt(bytes.fromhex(token))
        decrypt_content = unpad(decrypt_content, AES.block_size)
        decrypt_content = decrypt_content.decode("utf8")
        user_id, channel_id, expire_time, random_str = decrypt_content.split("||")
        return int(user_id), channel_id, expire_time, random_str
    except Exception:
        return None, None, None, None


async def encrypt_url(url: str):
    """
    使用ARC4加密url
    :param url:
    :return:
    """
    cipher = ARC4.new(MU38_TOKEN_AES_KEY)
    return cipher.encrypt(url.encode("utf8")).hex()


@alru_cache(maxsize=4096)
async def decrypt_url(url: str) -> str:
    """
    使用ARC4解密url
    :param url:
    :return:
    """
    cipher = ARC4.new(MU38_TOKEN_AES_KEY)
    return cipher.decrypt(bytes.fromhex(url)).decode("utf8")


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
    """
    生成高强度、易输入的token
    - 使用secrets生成密码学安全的随机字节
    - Base32编码确保可读性
    - 移除易混淆字符：I, L, O, 0, 1
    """
    excluded_chars = {"I", "L", "O", "0", "1"}
    min_length = length - 2  # 考虑到过滤后的最小长度
    while True:
        raw = secrets.token_bytes(length)
        token = base64.b32encode(raw).decode("utf-8").rstrip("=")[:10]
        # 过滤易混淆字符
        filtered = "".join(c for c in token if c not in excluded_chars)
        if len(filtered) < min_length:
            continue  # 长度不够重来
        return filtered[:min_length]
    # 对静态类型检查器可见的不可达分支
    raise RuntimeError("unreachable")


def aes_gcm_encrypt(plaintext: bytes, key: bytes) -> str:
    # key: 16/24/32 字节（AES-128/192/256）
    aes_gcm = AESGCM(key)
    nonce = os.urandom(12)  # 每次随机
    ciphertext = aes_gcm.encrypt(nonce, plaintext, None)
    # 拼接 nonce + ciphertext，然后 hex
    return (nonce + ciphertext).hex()


def aes_gcm_decrypt(token_hex: str, key: bytes) -> str:
    try:
        data = bytes.fromhex(token_hex)
        nonce, ciphertext = data[:12], data[12:]
        aes_gcm = AESGCM(key)
        result = aes_gcm.decrypt(nonce, ciphertext, None)
        return result.decode("utf-8")
    except Exception:
        return ""
