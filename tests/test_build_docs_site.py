"""The docs-site staging script's Traditional Chinese conversion."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-docs-site.py"


def load_stager() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_docs_site", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the docs-site staging script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConvertMarkdownTest(unittest.TestCase):
    """Prose becomes Traditional Chinese with Taiwan vocabulary; code and outside URLs stay as written."""

    def setUp(self) -> None:
        stager = load_stager()
        convert = stager.converter(stager.CONVERTED_LOCALES["zh-Hant"][1])
        self.convert = lambda text: stager.convert_markdown(text, convert)

    def test_prose_and_headings_use_taiwan_vocabulary(self) -> None:
        self.assertEqual("## 前臺命令\n\n普通函式在事件迴圈裡呼叫。\n", self.convert("## 前台命令\n\n普通函数在事件循环里调用。\n"))

    def test_code_blocks_and_code_spans_stay_as_written(self) -> None:
        page = '调用 `tui.ask("默认值")` 即可：\n\n```python\n# 默认配置\nname = "软件"\n```\n'
        self.assertEqual('呼叫 `tui.ask("默认值")` 即可：\n\n```python\n# 默认配置\nname = "软件"\n```\n', self.convert(page))

    def test_relative_anchors_follow_the_converted_headings(self) -> None:
        self.assertEqual(
            "見[前臺命令](background.md#前臺命令)和[本頁](#後臺任務)。", self.convert("见[前台命令](background.md#前台命令)和[本页](#后台任务)。")
        )

    def test_links_to_other_sites_stay_as_written(self) -> None:
        link = "[源码](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/users/admin.md#找回密码)"
        self.assertEqual(link.replace("[源码]", "[原始碼]"), self.convert(link))


if __name__ == "__main__":
    unittest.main()
