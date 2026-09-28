import os
import secrets
import string
import unicodedata
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse
from xml.sax.saxutils import escape

import orjson
from slugify import slugify

# clean_text 删除的格式字符（Unicode Cf）：只影响方向、断行，或者根本不显示。其余的 Cf 保留：ZWJ、ZWNJ、
# 蒙古文元音分隔符、埃及象形文字的组合符等决定相邻字符怎么拼（删掉 ZWJ 会把 emoji 家庭拆成三个人，删掉 ZWNJ
# 会改变波斯文的字形），阿拉伯文的数字符号、经文结束符本身就显示出来。
_INVISIBLE_FORMAT_CHARACTERS = frozenset(
    "\u00ad"  # 软连字符
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"  # 方向标记、嵌入与隔离
    "\u200b\u2060\ufeff"  # 零宽空格、词连接符、BOM
    "\u2061\u2062\u2063\u2064"  # 不可见的数学运算符
    "\u206a\u206b\u206c\u206d\u206e\u206f"  # 已弃用的格式符
    "\ufff9\ufffa\ufffb"  # 行间注释标记
    "\U000e0001"  # 语言标签（已弃用）
)
_BLACK_FLAG = "\U0001f3f4"
_CANCEL_TAG = "\U000e007f"


def _is_tag(char: str) -> bool:
    return "\U000e0020" <= char <= _CANCEL_TAG


def clean_text(value: bytes | str) -> str:
    """把外部来的文本（抓取的标题、M3U 里的频道名等）清洗成干净的单行文本。

    - bytes 按 UTF-8 解码，无法解码的字节丢弃；
    - 各种空白（换行、制表、不换行空格 ``\\xa0``、全角空格 ``\\u3000``、行分隔符等）换成普通空格，
      连续的合并成一个，首尾去掉——不会把两边的词粘在一起；
    - 控制字符删除；不显示的格式字符（零宽空格、BOM、方向标记与嵌入、软连字符、词连接符等）删除。决定相邻字符
      怎么拼的格式字符（emoji 序列的 ZWJ、波斯文的 ZWNJ、地区旗帜的标签序列）和本身显示的（阿拉伯数字符号）保留。

    >>> clean_text("第一行\\n第二行\\tA\\xa0B\\u3000C\\u200bD".encode())
    '第一行 第二行 A B CD'
    """
    text = value.decode(errors="ignore") if isinstance(value, bytes) else value
    kept: list[str] = []
    for char in text:
        if char.isspace():
            kept.append(" ")
        elif _is_tag(char):
            # 标签字符只在 🏴 后面拼成地区旗帜（英格兰、苏格兰、威尔士）时保留，到取消标签为止；
            # 单独出现的删除：它们不显示，能在文本里藏一段看不见的话。
            if kept and (kept[-1] == _BLACK_FLAG or (_is_tag(kept[-1]) and kept[-1] != _CANCEL_TAG)):
                kept.append(char)
        elif unicodedata.category(char) != "Cc" and char not in _INVISIBLE_FORMAT_CHARACTERS:
            kept.append(char)
    return " ".join("".join(kept).split())


def json_dumps(data: Any, *, option: int | None = None) -> str:
    """把数据编码成 JSON 字符串（orjson 只返回 bytes）。

    ``option`` 原样传给 ``orjson.dumps``，例如 ``orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS``。
    非 ASCII 字符原样输出，不转义成 ``\\uXXXX``。
    """
    return orjson.dumps(data, option=option).decode("utf-8")


def get_ext_from_filename(filename: str) -> str:
    """
    从文件名或URL中提取扩展名,支持复杂URL场景

    :param filename: 文件名或URL
    :return: 标准化的扩展名(小写,含点),若无扩展名则返回空字符串

    Examples:
        >>> get_ext_from_filename("video.mp4")
        '.mp4'
        >>> get_ext_from_filename("https://example.com/file.MP4?token=abc#anchor")
        '.mp4'
        >>> get_ext_from_filename("http://192.0.2.1:14017")
        ''
        >>> get_ext_from_filename("http://example.com:8080/path/video.mp4")
        '.mp4'
        >>> get_ext_from_filename("document")
        ''
        >>> get_ext_from_filename("archive.tar.gz")
        '.gz'
    """
    if not filename or not isinstance(filename, str):
        return ""

    _, ext = os.path.splitext(_name_part(filename))
    ext = ext.lower().strip()

    # 只认字母数字组成的扩展名
    if len(ext) > 1 and all(c.isalnum() or c == "." for c in ext):
        return ext
    return ""


def _name_part(filename: str) -> str:
    """取出带扩展名的那部分：URL 取路径（不含查询参数和片段），普通文件名去掉 ? 与 # 之后的内容；结尾的 / 去掉。"""
    clean_filename = filename.strip()
    parsed = urlparse(clean_filename)
    if parsed.scheme:
        return parsed.path.rstrip("/")
    for delimiter in ("?", "#"):
        clean_filename = clean_filename.split(delimiter)[0]
    return clean_filename.rstrip("/")


def get_full_ext_from_filename(filename: str) -> str:
    """提取扩展名；``.tar.gz``、``.tar.bz2``、``.tar.xz`` 这类打包再压缩的复合扩展名整体返回。

    只有压缩扩展名前面紧跟 ``.tar`` 才算复合：``backup.tar.gz`` 返回 ``.tar.gz``，
    ``report.2024.gz`` 返回 ``.gz``。
    """
    base_ext = get_ext_from_filename(filename)
    if base_ext in (".gz", ".bz2", ".xz"):
        stem, _ = os.path.splitext(_name_part(filename))
        if stem.lower().endswith(".tar"):
            return f".tar{base_ext}"
    return base_ext


def match_url(url: str, pattern: str) -> bool:
    """
    Match a URL against a pattern, supporting wildcards (*).

    Args:
        url: The URL to check
        pattern: The pattern to match against, can contain * wildcards

    Returns:
        bool: True if the URL matches the pattern, False otherwise
    """
    # Handle exact match case
    if "*" not in pattern:
        return url == pattern

    # Convert pattern to regex pattern
    # Escape special regex chars except * which we'll convert
    import re

    regex_pattern = re.escape(pattern).replace("\\*", ".*")
    # Ensure it matches the full string
    regex_pattern = f"^{regex_pattern}$"

    return bool(re.match(regex_pattern, url))


def escape_url_for_xml(url: str) -> str:
    # 将 & < > " ' 等转义为 XML 实体（例如 & -> &amp;）
    return escape(url, {'"': "&quot;", "'": "&apos;"})


def unique_slugs(names: list[str]) -> list[str]:
    """为一组名称逐个生成 slug，返回与 names 一一对应的列表；重名或 slugify 后相同的自动加 -1、-2……

    同名输入各自得到自己的 slug，调用方按位置配对（``zip(items, unique_slugs(names))``）::

        >>> unique_slugs(["HBO", "HBO", "HBO Max", "hbo-max"])
        ['hbo', 'hbo-1', 'hbo-max', 'hbo-max-1']

    先出现的保留原始 slug，所以同一份输入在顺序不变时结果稳定。slugify 后为空的名称（如 "!!!"）
    同样参与编号：第一个得到 ""，之后依次是 "-1"、"-2"。
    """
    # 每个 base_slug 上次用到的编号，冲突时从它的下一个接着试
    last_suffix: defaultdict[str, int] = defaultdict(int)
    used_slugs: set[str] = set()
    slugs: list[str] = []

    for name in names:
        base_slug = slugify(name)
        unique_slug = base_slug
        while unique_slug in used_slugs:
            last_suffix[base_slug] += 1
            unique_slug = f"{base_slug}-{last_suffix[base_slug]}"
        used_slugs.add(unique_slug)
        slugs.append(unique_slug)

    return slugs


def random_string(length: int, chars: str | None = None) -> str:
    """
    生成指定长度的随机字符串。

    Args:
        length: 要生成的字符串长度，必须为非负整数。
        chars: 可选的字符集字符串，若为 None 则使用大小写字母与数字。

    Returns:
        指定长度的随机字符串。

    Raises:
        TypeError: 如果 length 不是 int。
        ValueError: 如果 length 为负数或 chars 为空字符串。
    """
    if not isinstance(length, int):
        raise TypeError("length must be an int")
    if length < 0:
        raise ValueError("length must be non-negative")
    if chars is None:
        chars = string.ascii_letters + string.digits
    if not chars:
        raise ValueError("chars must be a non-empty string")

    return "".join(secrets.choice(chars) for _ in range(length))
