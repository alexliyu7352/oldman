"""
@author:alex
@date:2025/6/29
@time:21:11
"""

__author__ = "alex"

import logging
import os
import sys
from pathlib import Path


def _find_project_root(start: Path | None = None) -> Path:
    """Discover an application root without ever falling back to the installed package."""
    markers = ("pyproject.toml", "setup.cfg", "setup.py", ".git")

    def is_install_path(path: Path) -> bool:
        path_text = path.as_posix().lower()
        return any(pattern in path_text for pattern in ("/site-packages/", "/dist-packages/", "/lib/python", "/.pyenv/", "/.local/share/uv/"))

    def search_up(path: Path) -> Path | None:
        current = path.expanduser().resolve()
        if is_install_path(current):
            return None
        for candidate in (current, *current.parents):
            if any((candidate / marker).exists() for marker in markers):
                return candidate
        return None

    # 1) 环境变量优先
    env_root = os.getenv("PROJECT_ROOT")
    if env_root:
        p = Path(env_root).expanduser().resolve()
        if p.is_dir():
            return p

    # 2) 当前工作目录(最常见情况)
    cwd = Path.cwd()
    found = search_up(cwd)
    if found:
        return found

    # 2) 显式起点
    if start:
        found = search_up(Path(start).resolve())
        if found:
            return found

    # 3) 新增: 尝试从主模块 (__main__) 的文件路径查找
    if hasattr(sys.modules["__main__"], "__file__"):
        main_file = sys.modules["__main__"].__file__
        if main_file:
            found = search_up(Path(main_file).resolve().parent)
            if found:
                return found

    # 4) 尝试从 sys.path[0],但排除明显的调试器路径
    if sys.path:
        path0 = Path(sys.path[0]).resolve()
        # ✅ 过滤掉 IDE 调试器路径
        exclude_patterns = ["pydev", "pycharm", "vscode", "debugger"]
        if not any(pattern in str(path0).lower() for pattern in exclude_patterns):
            found = search_up(path0)
            if found:
                return found

    # 5) Markerless applications still own their current working directory.
    # Never derive writable defaults from oldman/conf inside site-packages.
    return cwd.resolve()


PROJECT_ROOT = _find_project_root()
BASE_PATH = BASE_DIR = PROJECT_ROOT

DEBUG = False

TEMPLATE_DEBUG = DEBUG

LOG_LEVEL: int = logging.INFO
LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT: int = 5

MEDIA_ROOT = BASE_DIR / "media"

MEDIA_URL = "/media/"

STATIC_ROOT = BASE_DIR / "static"

STATIC_URL = "/static/"

DOMAIN = "http://localhost:17998"

LOGS_DIR = BASE_DIR / "logs"

DATA_DIR = BASE_DIR / "data"

# 当前时区
TIME_ZONE = "Asia/Singapore"

PROXY_CONNECT_TIMEOUT = 5  # 代理连接超时

PROXY_READ_TIMEOUT = 10  # 代理读取超时

DEBUG_PROXY = "http://127.0.0.1:8118"

DEFAULT_LISTEN_PORT = 17998
DEFAULT_LISTEN_HOST = "::"
DEFAULT_WORKERS = 1
DEFAULT_ACCESS_LOG = False
# 是否文件更改自动重载
DEFAULT_AUTO_RELOAD = DEBUG

USER_AGENT_DICT_DEFINE = {
    "browsers": [
        "Google",
        "Chrome",
        "Firefox",
        "Edge",
        "Opera",
        "Safari",
        "Android",
        "Yandex Browser",
        "Samsung Internet",
        "Opera Mobile",
        "Mobile Safari",
        "Firefox Mobile",
        "Firefox iOS",
        "Chrome Mobile",
        "Chrome Mobile iOS",
        "Mobile Safari UI/WKWebView",
        "Edge Mobile",
        "DuckDuckGo Mobile",
        "MiuiBrowser",
        "Whale",
        "Twitter",
        "Facebook",
        "Amazon Silk",
    ],
    "os": [
        "Windows",
        "Linux",
        "Ubuntu",
        "Chrome OS",
        "Mac OS X",
        "Android",
        "iOS",
    ],
    "platforms": ["desktop", "mobile", "tablet"],
}

USER_AGENT_DEFINE = "okhttp/3.8.7"

HTTP_POOL_MAX_CONNECTIONS = 300

USE_HTTP_POOL = False
