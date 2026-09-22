import os
import secrets
import string
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from xml.sax.saxutils import escape

import orjson
from slugify import slugify


def filter_bytes(byte_string: bytes) -> str:
    """
    过滤字符串中的非法字符, 以及乱码
    :param byte_string: bytes
    :return: str
    """
    # Decode bytes to string_tpl
    string_tpl = byte_string.decode(errors="ignore")

    # Filter out the garbled text
    string_tpl = string_tpl.replace("\n", "").replace("\r", "").replace("\t", "")
    string_tpl = string_tpl.replace("\u200b", "").replace("\xa0", "")
    string_tpl = string_tpl.replace("\u3000", "").replace("\u2028", "")
    string_tpl = string_tpl.replace("\u200e", "").replace("\u202a", "")
    string_tpl = string_tpl.replace("\u200f", "").replace("\u2061", "")
    string_tpl = string_tpl.replace("\u3000", "").replace("\ufeff", "")
    string_tpl = string_tpl.replace("\u202c", "").replace("\u2060", "")
    string_tpl = string_tpl.replace("\u2063", "").replace("\x1a", "")
    string_tpl = string_tpl.replace("\x00", "").replace("\x01", "")
    string_tpl = string_tpl.replace("\x02", "").replace("\x03", "")
    string_tpl = string_tpl.replace("\x04", "").replace("\x05", "")
    string_tpl = string_tpl.replace("\x06", "").replace("\x07", "")
    string_tpl = string_tpl.replace("\x08", "").replace("\x09", "")
    string_tpl = string_tpl.replace("\x0a", "").replace("\x0b", "")
    string_tpl = string_tpl.replace("\x0c", "").replace("\x0d", "")
    string_tpl = string_tpl.replace("\x0e", "").replace("\x0f", "")
    string_tpl = string_tpl.replace("\x10", "").replace("\x11", "")
    string_tpl = string_tpl.replace("\x12", "").replace("\x13", "")
    string_tpl = string_tpl.replace("\x14", "").replace("\x15", "")
    string_tpl = string_tpl.replace("\x16", "").replace("\x17", "")
    string_tpl = string_tpl.replace("\x18", "").replace("\x19", "")
    string_tpl = string_tpl.replace("\x1b", "").replace("\x1c", "")
    string_tpl = string_tpl.replace("\x1d", "").replace("\x1e", "")
    string_tpl = string_tpl.replace("\x1f", "")
    return string_tpl.strip()


def json_dumps(data: dict, **kwargs: Any) -> str:
    """
    将dict转换为json字符串
    :param data:
    :param kwargs:
    :return:
    """
    if kwargs:
        raise TypeError("json_dumps does not forward options; call orjson.dumps directly for them")
    return orjson.dumps(data).decode("utf-8")


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

    clean_filename = filename.strip()

    # 1. 判断是否为URL
    parsed = urlparse(clean_filename)
    if parsed.scheme:  # 是URL
        # 提取路径部分,移除查询参数和片段
        path = parsed.path.rstrip("/")
        if not path or path == "/":
            return ""  # 无路径或根路径,无扩展名
        clean_filename = path
    else:
        # 2. 非URL的普通文件名,移除查询参数
        for delimiter in ["?", "#", "$"]:
            if delimiter in clean_filename:
                clean_filename = clean_filename.split(delimiter)[0]
        clean_filename = clean_filename.rstrip("/")

    # 3. 提取扩展名
    _, ext = os.path.splitext(clean_filename)

    # 4. 标准化处理
    ext = ext.lower().strip()

    # 5. 验证扩展名合法性
    if ext and len(ext) > 1:
        # 检查是否只包含字母数字和点
        if all(c.isalnum() or c == "." for c in ext):
            return ext

    return ""


# 若需支持复合扩展名(如 .tar.gz)
def get_full_ext_from_filename(filename: str) -> str:
    """提取复合扩展名"""
    base_ext = get_ext_from_filename(filename)
    if base_ext in [".gz", ".bz2", ".xz"]:
        # 使用urlparse处理URL
        parsed = urlparse(filename)
        clean_filename = parsed.path if parsed.scheme else filename

        parts = clean_filename.rsplit(".", 2)
        if len(parts) == 3:
            return f".{parts[1]}{base_ext}"
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


def get_url_from_params(base_url: str, params: dict, function_params: list[str], doseq: bool = True) -> str:
    """
    构建完整的代理URL
    :param doseq:
    :param function_params:
    :param base_url: 基础URL
    :param params: URL参数字典
    :return: 完整的代理URL
    """
    # 过滤掉函数使用的参数，剩余的都是url的参数
    url_params = {}
    for key, value in params.items():
        if key not in function_params:
            url_params[key] = value
    if url_params:
        # 检查base_url是否已包含参数
        if "?" in base_url:
            return f"{base_url}&{urlencode(url_params, doseq=doseq)}"
        else:
            return f"{base_url}?{urlencode(url_params, doseq=doseq)}"
    return base_url


def get_url_from_query_string(base_url: str, query_string: str, function_params: list[str], doseq: bool = True) -> str:
    """
    构建完整的代理URL
    :param doseq:
    :param function_params:
    :param base_url: 基础URL
    :param query_string: URL参数字符串
    :return: 完整的代理URL
    """
    # 过滤掉函数使用的参数，剩余的都是url的参数
    url_params = {}
    query_items = parse_qs(query_string, keep_blank_values=True)
    for key, value in query_items.items():
        if key not in function_params:
            url_params[key] = value
    if url_params:
        # 检查base_url是否已包含参数
        params_strings = urlencode(url_params, doseq)
        # 取消转义
        # params_strings = unquote(params_strings)
        if "?" in base_url:
            return f"{base_url}&{params_strings}"
        else:
            return f"{base_url}?{params_strings}"
    return base_url


def escape_url_for_xml(url: str) -> str:
    # 将 & < > " ' 等转义为 XML 实体（例如 & -> &amp;）
    return escape(url, {'"': "&quot;", "'": "&apos;"})


def generate_unique_slugs(
    names: list[str],
) -> tuple[dict[str, str], dict[str, int]]:
    """
    为一组名称生成唯一的 slug,自动处理冲突

    Args:
        names: 名称列表

    Returns:
        tuple: (name_to_slug 映射, slug_counter 计数器)
            - name_to_slug: {原始名称: 唯一slug}
            - slug_counter: {base_slug: 当前计数} (可用于调试)

    Example:
        >>> names = ["HBO", "HBO", "HBO Max"]
        >>> name_to_slug, _ = generate_unique_slugs(names)
        >>> print(name_to_slug)
        {'HBO': 'hbo', 'HBO': 'hbo-1', 'HBO Max': 'hbo-max'}
    """
    slug_counter: dict[str, int] = {}
    used_slugs: set[str] = set()
    name_to_slug: dict[str, str] = {}

    for name in names:
        base_slug = slugify(name)

        # 生成唯一 slug
        if base_slug not in used_slugs:
            unique_slug = base_slug
            slug_counter[base_slug] = 0
        else:
            # 使用 .get() 防止 KeyError
            counter: int = slug_counter.get(base_slug, 0)
            counter += 1
            unique_slug = f"{base_slug}-{counter}"

            # 处理连续冲突
            while unique_slug in used_slugs:
                counter += 1
                unique_slug = f"{base_slug}-{counter}"

            slug_counter[base_slug] = counter

        used_slugs.add(unique_slug)
        name_to_slug[name] = unique_slug

    return name_to_slug, slug_counter


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
