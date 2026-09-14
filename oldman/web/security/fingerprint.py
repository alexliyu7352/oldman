"""
@author:alex
@date:2025/11/25
@time:07:26
"""

__author__ = "alex"

import json
import time

from oldman.logging import logger
from oldman.providers.redis import redis_client
from oldman.serializers import MsgspecModel
from oldman.web.response import json_response
from oldman.web.security.decryptors import AESGcmDecrypt


class FakeLog(MsgspecModel):
    reason: str
    timestamp: int


def validate_payload(payload: dict, max_diff: int) -> tuple[bool, str, str]:
    """验证解密后的数据"""
    if "vid" not in payload or "ts" not in payload:
        return False, "missing_fields", ""

    visitor_id = payload["vid"]
    timestamp = payload["ts"]

    if not isinstance(visitor_id, str) or len(visitor_id) < 15:
        return False, "invalid_visitor_id", ""

    current_time = int(time.time() * 1000)
    if abs(current_time - timestamp) > max_diff:
        return False, "timestamp_expired", ""

    return True, "valid", visitor_id


async def log_fake_fingerprint_attempt(ip: str, reason: str):
    """记录伪造指纹尝试"""
    log_key = f"fake_attempts:{ip}"
    log_data = FakeLog(timestamp=int(time.time()), reason=reason)
    conn = await redis_client.async_get_conn()

    await conn.lpush(log_key, log_data.to_msgpack())
    await conn.ltrim(log_key, 0, 99)
    await conn.expire(log_key, 86400)

    # 如果同一IP频繁伪造，直接拉黑
    attempt_count = await conn.llen(log_key)
    if attempt_count > 10:  # 10次伪造尝试
        blacklist_key = f"blacklist:ip:{ip}"
        await conn.setex(blacklist_key, 3600, "fake_fingerprint")
        logger.warning(f"IP已拉黑（伪造指纹）: {ip}")


def get_fingerprint_from_front(encrypted_b64: str, aes_secret_key: str, max_diff: int) -> tuple[str, str]:
    """从解密后的数据中提取指纹"""
    success, msg, payload = AESGcmDecrypt.decrypt(encrypted_b64, aes_secret_key)
    if not success:
        logger.warning(f"Fingerprint decryption failed: {msg}")
        return "", msg
    valid, error_msg, visitor_id = validate_payload(payload, max_diff)
    if not valid:
        logger.warning(f"Fingerprint validation failed: {error_msg}")
        return "", error_msg
    return visitor_id, "success"


async def get_stats(fingerprint: str):
    """管理接口 - 查看指纹统计"""
    conn = await redis_client.async_get_conn()

    # 获取关联IP
    fp_ip_key = f"relation:fp_ip:{fingerprint}"
    ips = await conn.smembers(fp_ip_key)

    # 获取异常日志
    anomaly_key = f"anomaly_log:{fingerprint}"
    anomaly_logs_raw = await conn.lrange(anomaly_key, 0, 9)
    anomaly_logs = [json.loads(log) for log in anomaly_logs_raw]

    # 获取拒绝日志
    blocked_key = f"blocked_log:{fingerprint}"
    blocked_logs_raw = await conn.lrange(blocked_key, 0, 9)
    blocked_logs = [json.loads(log) for log in blocked_logs_raw]

    # 检查黑名单状态
    fp_blacklist_key = f"blacklist:fp:{fingerprint}"
    is_blocked = await conn.exists(fp_blacklist_key)

    return json_response(
        {
            "error_code": 0,
            "data": {
                "fingerprint": fingerprint,
                "is_blocked": bool(is_blocked),
                "associated_ips": list(ips),
                "ip_count": len(ips),
                "recent_anomalies": anomaly_logs,
                "recent_blocks": blocked_logs,
            },
        }
    )
