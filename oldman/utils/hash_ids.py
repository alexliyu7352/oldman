import random

from sqids import Sqids

# 官方示例里的默认 alphabet，可以直接拿来用 [page:1]
DEFAULT_ALPHABET = "k3G7QAe51FCsPW92uEOyq4Bg6Sp8YzVTmnU0liwDdHXLajZrfxNhobJIRcMvKt"
SQIDS_ALPHABET = "RJZeNf2isxqOdA1myUjr85uh3LGpSMTlQP7W4CoYIDcb09wazHKtgk6FBvnXEV"
SQIDS_MIN_LENGTH = 8

_sqids = Sqids(
    alphabet=SQIDS_ALPHABET,
    min_length=SQIDS_MIN_LENGTH,
)


def generate_alphabet(
        remove_chars: str = "",
        seed: int | None = None,
) -> str:
    """
    生成一个用于 Sqids 的自定义 alphabet。
    - remove_chars: 要从默认 alphabet 中剔除的字符，例如 "aeiouAEIOU01".
    - seed: 指定随机种子以便复现；生产环境建议不传，改为一次生成后写死。
    """
    chars = [c for c in DEFAULT_ALPHABET if c not in set(remove_chars)]
    if len(chars) < 3:
        raise ValueError("alphabet 长度至少为 3 个字符")  # Sqids 限制 [web:39]

    rng = random.Random(seed)
    rng.shuffle(chars)
    return "".join(chars)


def encode_id(num_id: int) -> str:
    """
    把单个非负整数 id 编码为字符串 id。
    """
    if num_id < 0:
        raise ValueError("Sqids 不支持负数 id")  # FAQ 提示 [web:39]
    return _sqids.encode([num_id])


def decode_id(pub_id: str, *, strict: bool = True) -> int | None:
    """
    从字符串 id 解码出整数 id。
    - strict=True 时会做“规范化校验”，防止人为构造的字符串被当作合法 id.
    """
    if not pub_id:
        return None

    numbers = _sqids.decode(pub_id)
    if not numbers:
        return None

    if strict:
        # 规范化：确保传入字符串就是 encode 产物 [web:39][web:43]
        normalized = _sqids.encode(numbers)
        if normalized != pub_id:
            return None

    return numbers[0]
