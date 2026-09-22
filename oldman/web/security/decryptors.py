"""Read the payload the browser's Web Crypto API produces.

Everything cryptographic lives in `oldman.utils.crypto`; what remains here is the wire
format that browser code and this framework agreed on — Base64 around the IV-prefixed
AES-GCM blob, JSON inside it — and the key material arriving Base64-encoded from settings.
"""

from __future__ import annotations

import base64

import orjson

from oldman.utils.crypto import aes_gcm_decrypt


class AESGcmDecrypt:
    """解密前端 Web Crypto API 加密的数据。"""

    @staticmethod
    def decrypt(encrypted_b64: str, aes_secret_key: str) -> tuple[bool, str, dict]:
        """Decode the browser envelope and return its JSON body.

        Wire format: Base64(IV[12] + ciphertext + tag[16]); the key arrives Base64 too.

        Returns `(ok, reason, payload)`. Reasons are passed through from the primitive
        unchanged except for the two this layer owns: a Base64 envelope that does not
        decode, and a plaintext that is not JSON.
        """
        try:
            encrypted_bytes = base64.b64decode(encrypted_b64)
            secret_key = base64.b64decode(aes_secret_key)
        except Exception as error:
            return False, f"invalid_encoding:{error}", {}

        ok, reason, plaintext = aes_gcm_decrypt(encrypted_bytes, secret_key)
        if not ok:
            return False, reason, {}

        try:
            # orjson 直接接受 bytes；它也是这个仓库其余解析路径用的解析器。
            return True, "success", orjson.loads(plaintext)
        except orjson.JSONDecodeError:
            return False, "invalid_json", {}
