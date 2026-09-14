import subprocess
import sys
from collections.abc import Iterable
from importlib.resources import as_file, files
from pathlib import Path
from tempfile import TemporaryDirectory

from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po, write_po

from oldman.i18n.frontend import (
    FrontendMessage,
    extract_project_frontend_messages,
    oldman_web_messages,
)

LOCALES_DIR = "locales"
POT_FILE = f"./{LOCALES_DIR}/messages.pot"
BABEL_CFG = "babel.cfg"
FRAMEWORK_BABEL_CFG = "i18n/framework-babel.cfg"
PYBABEL_COMMAND = [sys.executable, "-m", "babel.messages.frontend"]

KEYWORDS = [
    # 标准单数翻译
    "-k",
    "_",
    "-k",
    "gettext",
    "-k",
    "gettext_noop",
    "-k",
    "ugettext",
    # 复数翻译
    "-k",
    "ngettext:1,2",
    "-k",
    "ungettext:1,2",
    # 上下文翻译
    "-k",
    "pgettext:1c,2",
    "-k",
    "npgettext:1c,2,3",
    # 域翻译
    "-k",
    "dgettext:2",
    "-k",
    "dngettext:2,3",
    # 标记函数
    "-k",
    "N_",
    # lazy 版本
    "-k",
    "gettext_lazy",
    "-k",
    "ngettext_lazy:1,2",
    "-k",
    "pgettext_lazy:1c,2",
    "-k",
    "npgettext_lazy:1c,2,3",
]


def _extract_catalog(
    *,
    config: str,
    output: Path,
    source: str,
    keywords: list[str],
    cwd: Path | None = None,
) -> None:
    """Run Babel extraction for one explicit source/config pair."""
    subprocess.run(
        [
            *PYBABEL_COMMAND,
            "extract",
            "-F",
            config,
            *keywords,
            "-o",
            str(output),
            source,
        ],
        check=True,
        cwd=cwd,
    )


def _add_frontend_messages(
    catalog: Catalog,
    messages: Iterable[FrontendMessage],
) -> None:
    """Merge typed frontend identities while rejecting plural drift."""
    for message in messages:
        existing = catalog.get(message.id, context=message.context)
        existing_plural = None
        if existing is not None and isinstance(existing.id, tuple):
            existing_plural = existing.id[1]
        if (
            existing_plural is not None
            and message.plural is not None
            and existing_plural != message.plural
        ):
            raise ValueError(
                f"Frontend message {message.id!r} has conflicting plural "
                f"forms {existing_plural!r} and {message.plural!r}."
            )
        catalog.add(
            message.babel_id,
            locations=[
                (location.path, location.line)
                for location in message.locations
            ],
            context=message.context,
        )


def _merge_catalogs(
    project_pot: Path,
    framework_pot: Path,
    output: Path,
    *,
    project_frontend_messages: Iterable[FrontendMessage] = (),
) -> None:
    """Merge Python, template, and generated frontend framework messages."""
    with project_pot.open("rb") as project_file:
        catalog = read_po(project_file)
    with framework_pot.open("rb") as framework_file:
        framework_catalog = read_po(framework_file)

    for message in framework_catalog:
        if not message.id:
            continue
        locations = []
        for filename, lineno in message.locations:
            normalized = filename.removeprefix("./")
            if not normalized.startswith("oldman/"):
                normalized = f"oldman/{normalized}"
            locations.append((normalized, lineno))
        catalog.add(
            message.id,
            message.string,
            locations=locations,
            flags=message.flags,
            auto_comments=message.auto_comments,
            user_comments=message.user_comments,
            previous_id=message.previous_id,
            context=message.context,
        )

    _add_frontend_messages(catalog, project_frontend_messages)
    _add_frontend_messages(catalog, oldman_web_messages())

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as output_file:
        write_po(output_file, catalog)


def extract() -> None:
    """提取项目和框架翻译字符串到同一个应用消息目录。"""
    output = Path(POT_FILE)
    project_root = Path.cwd().resolve()
    project_frontend_messages = extract_project_frontend_messages(
        project_root
    )
    with TemporaryDirectory(prefix="oldman-i18n-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        project_pot = temporary_path / "project.pot"
        framework_pot = temporary_path / "framework.pot"

        _extract_catalog(
            config=BABEL_CFG,
            output=project_pot,
            source=".",
            keywords=KEYWORDS,
        )
        with as_file(files("oldman")) as framework_root:
            _extract_catalog(
                config=f"{framework_root.name}/{FRAMEWORK_BABEL_CFG}",
                output=framework_pot,
                source=framework_root.name,
                keywords=KEYWORDS,
                cwd=framework_root.parent,
            )
        _merge_catalogs(
            project_pot,
            framework_pot,
            output,
            project_frontend_messages=project_frontend_messages,
        )


def init(locale: str) -> None:
    """初始化新语言"""
    subprocess.run([*PYBABEL_COMMAND, "init", "-i", POT_FILE, "-d", LOCALES_DIR, "-l", locale], check=True)


def update() -> None:
    """更新翻译"""
    extract()
    subprocess.run([*PYBABEL_COMMAND, "update", "-i", POT_FILE, "-d", LOCALES_DIR], check=True)


def compile_translations() -> None:
    """编译翻译"""
    subprocess.run([*PYBABEL_COMMAND, "compile", "-d", LOCALES_DIR], check=True)
