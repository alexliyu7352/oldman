import os
import secrets
import stat
from pathlib import Path
from typing import Any

import orjson

from oldman.logging import get_logger

logger = get_logger(__name__)


def atomic_write(
    path: str | os.PathLike[str],
    data: bytes | str,
    *,
    follow_symlinks: bool,
    new_file_mode: int = 0o666,
) -> os.stat_result:
    """Replace a file's contents in one step: readers see the old file or the new one, never half of it.

    The contents go to a uniquely named sibling first and are then moved over the target, so a
    crash leaves the old file intact and two writers never share a temporary file. The temporary
    file reaches the disk before the rename and the directory after it, so a power loss leaves
    either the old contents or the new ones, not an empty file.

    Permissions: an existing file keeps its mode; a new one is created with ``new_file_mode``
    through the umask, like ``open()`` — pass ``0o600`` for a file that holds secrets. Setting the
    mode on a filesystem without permissions is logged, not fatal. Missing parent directories are
    created; ``str`` data is written as UTF-8.

    Returns the ``stat`` of the file this call wrote, taken from its own handle: a caller that
    records it (to notice later changes) never mistakes a file another writer swapped in right
    after the rename for its own.

    ``follow_symlinks`` has no default because the caller has to decide what a link at ``path``
    means. True writes the file the link points to - next to it, then over it - and keeps the link,
    as writing through the link did: settings files several services share by linking to one.
    The replaced file then belongs to the user who wrote it. False replaces the link itself with
    a regular file, for callers that refuse links anyway (the static files collector).
    """
    target = Path(os.path.realpath(path)) if follow_symlinks else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    try:
        existing_mode: int | None = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        existing_mode = None
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    # A new target is created with new_file_mode through the umask, as open() would. Replacing an
    # existing one starts owner-only and takes the target's mode before any content is written.
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, new_file_mode if existing_mode is None else 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            if existing_mode is not None:
                _copy_mode(file.fileno(), existing_mode, temporary)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
            written = os.fstat(file.fileno())
        temporary.replace(target)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # The original failure is what the caller needs; a leftover temporary file is only logged.
            logger.warning("Could not remove temporary file %s", temporary, exc_info=True)
        raise
    _fsync_directory(target.parent)
    return written


def _copy_mode(descriptor: int, mode: int, temporary: Path) -> None:
    """Give the temporary file the target's mode; filesystems without permissions only log."""
    try:
        os.fchmod(descriptor, mode)
    except OSError:
        logger.warning("Could not set mode %s on %s", oct(mode), temporary, exc_info=True)


def _fsync_directory(directory: Path) -> None:
    """Flush the directory entry so the rename survives a power loss.

    The rename has already happened, so a failure here is logged rather than turning a completed
    write into an error.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        logger.warning("Could not flush directory %s", directory, exc_info=True)


def check_file_mtime(filename: str | os.PathLike[str], old_time: float | None) -> tuple[bool, float]:
    """文件的修改时间是否比 old_time 新；返回 (是否变了, 应当记下的修改时间)。

    old_time 为 None 表示第一次检查：记下当前修改时间，不算变化。文件不存在时抛 FileNotFoundError。
    只读一次文件元数据，是普通的同步调用——事件循环里频繁调用时放进 ``asyncio.to_thread``。
    """
    mtime = os.stat(filename).st_mtime
    if old_time is None:
        return False, mtime
    if mtime > old_time:
        return True, mtime
    return False, old_time


def load_json_file(file_path: str | os.PathLike[str]) -> Any | None:
    """读取 JSON 文件；文件不存在时返回 None。

    内容不是合法 JSON 时抛 ``orjson.JSONDecodeError``（ValueError 的子类），不返回 None：否则调用方会以为
    “没有文件”，接着写默认值把原文件覆盖掉。
    """
    try:
        content = Path(file_path).read_bytes()
    except FileNotFoundError:
        return None
    return orjson.loads(content)


def save_json_file(data: Any, file_path: str | os.PathLike[str]) -> None:
    """写成缩进两格的 UTF-8 JSON，整体替换原文件（见 atomic_write）；父目录不存在时创建，失败抛异常。"""
    atomic_write(file_path, orjson.dumps(data, option=orjson.OPT_INDENT_2), follow_symlinks=True)
