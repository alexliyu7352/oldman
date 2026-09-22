"""
@author:alex
@date:2025/6/29
@time:21:11
"""

__author__ = "alex"

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

# 保留下来的开关。其余曾经住在这里的常量都已移除：它们与 oldman/conf/schemas.py 里的
# Pydantic 默认值一字不差地重复，而改 schema 并不会同步这里，于是两份会慢慢对不上。
# 配置的唯一来源是 settings，不是这个模块。
DEBUG = False

TEMPLATE_DEBUG = DEBUG

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
