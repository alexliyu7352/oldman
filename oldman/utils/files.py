import os
from typing import Any

import orjson

from oldman.logging import logger


async def check_file_mtime(filename: str, old_time: float) -> tuple[bool, float]:
    file_changed = False
    stat = os.stat(filename)
    mtime = stat.st_mtime
    if old_time is None:
        old_time = mtime
    elif mtime > old_time:
        old_time = mtime
        file_changed = True
    return file_changed, old_time


def load_json_file(file_path: str) -> Any | None:
    try:
        with open(file_path, encoding="utf-8") as f:
            return orjson.loads(f.read())
    except FileNotFoundError:
        logger.info(f"文件 {file_path} 未找到")
        return None
    except orjson.JSONDecodeError:
        logger.info(f"文件 {file_path} 解析失败")
        return None


def save_json_file(data: Any, file_path: str) -> None:
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            # orjson 输出 UTF-8 且不转义非 ASCII，等价于 ensure_ascii=False。
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode("utf-8"))
    except Exception as e:
        logger.info(f"保存文件 {file_path} 失败: {e}")
