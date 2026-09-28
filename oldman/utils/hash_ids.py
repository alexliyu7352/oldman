"""公开 id 的编码：把自增整数 id 编成不连续、不易猜的短字符串（Sqids），放进 URL 而不暴露数量与顺序。

这是混淆，不是加密。字母表按部署区分，取自 ``settings.core.id_alphabet``：Web 服务的设置同步会生成它，
同一项目里其他要编码或解码 id 的服务复制同一个值。换字母表会让已经发出去的 id 全部失效。
"""

import random
import secrets
from functools import lru_cache

from sqids import Sqids

# Sqids 默认字母表(a-z A-Z 0-9)的一个乱序排列。generate_alphabet 从它剔除字符后再打乱;
# 传同一个 seed 能复现同一个结果,前提是这里的顺序不变——所以不要改动它。
DEFAULT_ALPHABET = "k3G7QAe51FCsPW92uEOyq4Bg6Sp8YzVTmnU0liwDdHXLajZrfxNhobJIRcMvKt"
SQIDS_MIN_LENGTH = 8


def _configured_sqids() -> Sqids:
    """按本服务配置的字母表构造的 Sqids；配置为空时说明该怎么补上。"""
    import oldman.conf as conf

    alphabet = conf.settings.core.id_alphabet
    if not alphabet:
        raise RuntimeError(
            "settings.core.id_alphabet is empty; run the Web service's settings sync command, "
            "and copy the same value into every other service that encodes or decodes ids"
        )
    return _sqids_for(alphabet)


@lru_cache(maxsize=4)
def _sqids_for(alphabet: str) -> Sqids:
    return Sqids(alphabet=alphabet, min_length=SQIDS_MIN_LENGTH)


def generate_alphabet(
    remove_chars: str = "",
    seed: int | None = None,
) -> str:
    """
    生成一个用于 Sqids 的自定义 alphabet。
    - remove_chars: 要从默认 alphabet 中剔除的字符，例如 "aeiouAEIOU01".
    - seed: 指定随机种子以便复现；不传时用系统随机源打乱（设置同步生成 ``core.id_alphabet`` 就是这样）。
    """
    chars = [c for c in DEFAULT_ALPHABET if c not in set(remove_chars)]
    if len(chars) < 3:
        raise ValueError("alphabet 长度至少为 3 个字符")  # Sqids 构造时的下限

    rng = random.Random(seed) if seed is not None else secrets.SystemRandom()
    rng.shuffle(chars)
    return "".join(chars)


def encode_id(num_id: int) -> str:
    """
    把单个非负整数 id 编码为字符串 id。
    """
    if num_id < 0:
        raise ValueError("Sqids 不支持负数 id")  # Sqids 只编码 0 到 2**63-1
    return _configured_sqids().encode([num_id])


def decode_id(pub_id: str, *, strict: bool = True) -> int | None:
    """
    从字符串 id 解码出整数 id。
    - strict=True 时会做“规范化校验”，防止人为构造的字符串被当作合法 id.
    """
    if not pub_id:
        return None

    sqids = _configured_sqids()
    numbers = sqids.decode(pub_id)
    # encode_id 只编码单个 id；解出多个数字说明不是它的产物，不能只取第一个当结果
    if len(numbers) != 1:
        return None

    if strict:
        # 规范化：确保传入字符串就是 encode 产物。Sqids 对非规范写法也可能解出数字,
        # 重新编码后比对,才能拒绝同一个 id 的其他写法
        normalized = sqids.encode(numbers)
        if normalized != pub_id:
            return None

    return numbers[0]
