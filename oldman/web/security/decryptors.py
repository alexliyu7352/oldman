"""Decrypt payloads produced by the browser Web Crypto API.

@author:alex
@date:2025/11/25
@time:07:13
"""

__author__ = "alex"

import base64

import ujson
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class AESGcmDecrypt:
    """解密前端Web Crypto API加密的数据"""

    @staticmethod
    def decrypt(encrypted_b64: str, aes_secret_key: str) -> tuple[bool, str, dict]:
        """
        解密AES-GCM加密的数据

        前端格式: Base64(IV[12字节] + 密文 + Tag[16字节])

        返回: (是否成功, 错误信息, 解密数据)
        """
        try:
            # 1. Base64解码
            encrypted_bytes = base64.b64decode(encrypted_b64)

            # 2. 分离IV和密文
            # AES-GCM: IV是12字节，Tag在密文末尾16字节
            if len(encrypted_bytes) < 28:  # 12 (IV) + 16 (Tag)
                return False, "data_too_short", {}

            iv = encrypted_bytes[:12]
            ciphertext_with_tag = encrypted_bytes[12:]

            # 3. 准备密钥
            secret_key = base64.b64decode(aes_secret_key)

            # 4\. 使用 AESGCM 解密
            aesgcm = AESGCM(secret_key)
            plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, None)

            # 5\. 解析 JSON
            payload = ujson.loads(plaintext.decode("utf-8"))

            return True, "success", payload

        except ujson.JSONDecodeError:
            return False, "invalid_json", {}
        except Exception as e:
            # cryptography 在认证失败、格式错误等情况下都会抛 ValueError

            msg = str(e)

            if "tag" in msg or "authentication" in msg:
                return False, f"authentication_failed:{msg}", {}

            return False, f"decryption_error:{msg}", {}
