"""从统一的 gettext 目录生成浏览器用的 JSON 语言包与语言清单。

住在 web 层是因为它要读 `web.static.url` 并生成浏览器资源；纯粹的目录编译在 `oldman.i18n.frontend`。

项目的前端在构建前需要两样东西：`public/i18n/<code>.json`（浏览器目录）和 `src/i18n/generated.ts`
（语言清单：默认语言、别名、旗标地址、目录路径）。两者都由项目的 `locales/*/LC_MESSAGES/messages.po`
和 `data/<service>_settings.yaml` 推导，所以由框架生成，不由每个项目各写一份脚本。

发布是原子的：先把新目录集合换上去，最后才换清单；中途失败会把旧目录集合放回原处。
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from ruamel.yaml import YAML

from oldman.conf.schemas import I18nConfig, StaticConfig
from oldman.i18n import LanguageRegistry, language_code_variants
from oldman.i18n.frontend import compile_project_frontend_catalog
from oldman.web.i18n.assets import direct_flag_url


def _language_mapping(
    languages: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Convert the serializable language list into core registry input."""
    return {str(language["code"]): language for language in languages}


def read_i18n_languages(
    settings_file: Path,
) -> tuple[str, list[dict[str, object]]]:
    """Read the canonical frontend language contract from project settings."""
    default_language, languages, _ = read_i18n_contract(settings_file)
    return default_language, languages


def read_i18n_contract(
    settings_file: Path,
) -> tuple[str, list[dict[str, object]], str]:
    """Read one consistent language and static-URL settings snapshot."""
    data = YAML(typ="safe", pure=True).load(settings_file.read_text(encoding="utf-8")) or {}
    i18n = I18nConfig.model_validate(data.get("i18n") or {})
    web = data.get("web") or {}
    static = StaticConfig.model_validate(web.get("static") or {})
    registry = LanguageRegistry(i18n.languages)
    if not registry:
        raise ValueError(f"{settings_file} 中的 i18n.languages 不能为空")
    languages = [
        {
            "aliases": list(definition.aliases),
            "babel_locale": definition.babel_locale,
            "code": definition.code,
            "flag": definition.flag,
            "locale": definition.code,
            "name": definition.name,
        }
        for definition in registry
    ]
    default_language = registry.resolve(i18n.default_language)
    if not default_language:
        raise ValueError(
            f"{settings_file} 中的 i18n.default_language 不属于 i18n.languages"
        )
    return default_language, languages, static.url


def build_language_aliases(
    languages: list[dict[str, object]],
) -> dict[str, str]:
    """Generate canonical browser aliases from the settings registry."""
    aliases: dict[str, str] = {}
    registry = LanguageRegistry(_language_mapping(languages))
    for definition in registry:
        for candidate in (definition.code, *definition.aliases):
            for variant in language_code_variants(candidate):
                aliases[variant] = definition.code
    return aliases


def js_string(value: str) -> str:
    """Serialize one Python string as a readable JavaScript literal."""
    return json.dumps(value, ensure_ascii=False)


def catalog_filename(language_code: str) -> str:
    """Convert one canonical language code into its catalog filename."""
    return language_code.lower()


def write_language_manifest(
    output_file: Path,
    settings_file: Path,
) -> None:
    """Generate the browser language index without duplicating locale identity."""
    default_language, languages, static_url = read_i18n_contract(settings_file)
    write_language_manifest_data(
        output_file,
        default_language,
        languages,
        static_url=static_url,
    )


def write_language_manifest_data(
    output_file: Path,
    default_language: str,
    languages: list[dict[str, object]],
    *,
    static_url: str,
) -> None:
    """Write a manifest from the same validated settings snapshot as catalogs."""
    aliases = build_language_aliases(languages)

    lines = [
        "export interface LanguageDefinition {",
        "  readonly code: string;",
        "  readonly locale: string;",
        "  readonly aliases: readonly string[];",
        "  readonly flag: string;",
        "  readonly flagUrl?: string;",
        "  readonly catalogPath: string;",
        "  readonly name: string;",
        "}",
        "",
        f"export const defaultLanguage = {js_string(default_language)};",
        "",
        "export const languageDefinitions = [",
    ]
    for language in languages:
        code = str(language["code"])
        raw_aliases = language["aliases"]
        language_aliases = (
            [str(alias) for alias in raw_aliases]
            if isinstance(raw_aliases, list)
            else []
        )
        flag = str(language["flag"])
        flag_url = direct_flag_url(flag, static_url=static_url)
        lines.extend(
            [
                "  {",
                f"    code: {js_string(code)},",
                f"    locale: {js_string(code)},",
                f"    aliases: {json.dumps(language_aliases, ensure_ascii=False)},",
                f"    flag: {js_string(flag)},",
            ]
        )
        lines.append(f"    flagUrl: {js_string(flag_url)},")
        lines.extend(
            [
                f"    catalogPath: {js_string('i18n/' + catalog_filename(code) + '.json')},",
                f"    name: {js_string(str(language['name']))},",
                "  },",
            ]
        )
    lines.extend(
        [
            "] as const satisfies readonly LanguageDefinition[];",
            "",
            "export const supportedLanguageCodes = languageDefinitions.map((language) => language.code);",
            "",
            "export const languageAliases: Record<string, string> = {",
        ]
    )
    for alias, code in sorted(aliases.items()):
        lines.append(f"  {js_string(alias)}: {js_string(code)},")
    lines.extend(
        [
            "};",
            "",
            "export const localeToLanguageCode: Record<string, string> = {",
        ]
    )
    for language in languages:
        code = str(language["code"])
        for variant in language_code_variants(code):
            lines.append(f"  {js_string(variant)}: {js_string(code)},")
    lines.extend(["};", ""])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines), encoding="utf-8")


def write_catalog_json(
    output_file: Path,
    catalog: Mapping[str, object],
) -> None:
    """Write one validated browser TranslationCatalog."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(dict(catalog), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_language_catalogs(
    output_dir: Path,
    locales_dir: Path,
    configured_languages: list[dict[str, object]],
    *,
    compiler_command: Sequence[str] | None = None,
    project_root: Path = Path.cwd(),
) -> None:
    """Compile the complete configured set from unified ``messages.po`` files."""
    for definition in configured_languages:
        language_code = str(definition["code"])
        babel_locale = str(definition["babel_locale"])
        po_file = (
            locales_dir
            / babel_locale
            / "LC_MESSAGES"
            / "messages.po"
        )
        if po_file.exists():
            catalog = compile_project_frontend_catalog(
                project_root,
                po_file,
                fallback_locale=language_code,
                compiler_command=compiler_command,
            )
            catalog["locale"] = language_code
        else:
            catalog = {"locale": language_code, "messages": {}}
        write_catalog_json(
            output_dir / f"{catalog_filename(language_code)}.json",
            catalog,
        )


def validate_catalog_directory(
    output_dir: Path,
    configured_languages: list[dict[str, object]],
) -> None:
    """Ensure staging contains exactly one valid catalog per configured language."""
    expected = {
        f"{catalog_filename(str(language['code']))}.json"
        for language in configured_languages
    }
    actual = {path.name for path in output_dir.glob("*.json")}
    if actual != expected:
        raise RuntimeError(
            "前端 catalog 集合不完整: "
            f"expected={sorted(expected)!r}, actual={sorted(actual)!r}"
        )

    for catalog_file in sorted(output_dir.glob("*.json")):
        try:
            payload = json.loads(catalog_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{catalog_file} 不是有效 JSON") from exc
        _validated_catalog(payload, catalog_file)


def publish_staged_i18n(
    staged_catalogs: Path,
    output_dir: Path,
    staged_manifest: Path,
    languages_output: Path,
) -> None:
    """先整体换掉目录集合，最后才换清单：清单描述的目录必须已经在位。"""
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    languages_output.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = staged_catalogs.parent / "previous-catalogs"
    had_previous_catalogs = output_dir.exists()
    if had_previous_catalogs and not output_dir.is_dir():
        raise RuntimeError(f"catalog 输出路径不是目录: {output_dir}")

    if had_previous_catalogs:
        output_dir.replace(backup_dir)
    try:
        staged_catalogs.replace(output_dir)
        staged_manifest.replace(languages_output)
    except Exception:
        # The old manifest remains until its atomic replace succeeds. Restore the
        # matching old catalog directory if the final publish step fails.
        if output_dir.exists():
            shutil.rmtree(output_dir)
        if had_previous_catalogs and backup_dir.exists():
            backup_dir.replace(output_dir)
        raise


def project_frontend_paths(project_root: Path, *, service: str = "web") -> dict[str, Path]:
    """项目约定的四个位置：settings、locales、浏览器目录输出、语言清单输出。"""
    return {
        "settings_file": project_root / "data" / f"{service}_settings.yaml",
        "locales_dir": project_root / "locales",
        "output_dir": project_root / "frontend" / "public" / "i18n",
        "languages_output": project_root / "frontend" / "src" / "i18n" / "generated.ts",
    }


def build_frontend_i18n(
    output_dir: Path,
    locales_dir: Path,
    settings_file: Path,
    languages_output: Path,
    *,
    compiler_command: Sequence[str] | None = None,
    project_root: Path = Path.cwd(),
) -> None:
    """按项目配置编译、校验并原子发布一整套浏览器语言包与清单。

    清单是前端 import 的 TypeScript 模块（`frontend/src/i18n/generated.ts`），语言集合因此随
    bundle 一起到达，启动不需要再取一次；代价是新增语言后必须重新构建前端。清单必须落在 catalog
    目录之外：发布那一步会整体替换目录。
    """
    if languages_output.parent.resolve() == output_dir.resolve():
        raise ValueError(
            f"语言清单不能放在 catalog 目录里（{languages_output}）：发布 {output_dir} 时会整体替换该目录。"
        )
    default_language, configured_languages, static_url = read_i18n_contract(
        settings_file
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    languages_output.parent.mkdir(parents=True, exist_ok=True)

    with (
        TemporaryDirectory(
            prefix=".oldman-i18n-catalogs-",
            dir=output_dir.parent,
        ) as catalog_temporary_directory,
        TemporaryDirectory(
            prefix=".oldman-i18n-manifest-",
            dir=languages_output.parent,
        ) as manifest_temporary_directory,
    ):
        staged_catalogs = Path(catalog_temporary_directory) / "catalogs"
        staged_manifest = Path(manifest_temporary_directory) / languages_output.name
        write_language_catalogs(
            staged_catalogs,
            locales_dir,
            configured_languages,
            compiler_command=compiler_command,
            project_root=project_root,
        )
        validate_catalog_directory(staged_catalogs, configured_languages)
        write_language_manifest_data(
            staged_manifest,
            default_language,
            configured_languages,
            static_url=static_url,
        )
        publish_staged_i18n(
            staged_catalogs,
            output_dir,
            staged_manifest,
            languages_output,
        )


def _validated_catalog(
    payload: object,
    source: Path,
) -> dict[str, object]:
    """Reject malformed compiler output before writing browser assets."""
    if not isinstance(payload, dict):
        raise RuntimeError(f"oldman-web-i18n 为 {source} 返回的 catalog 不是对象")
    locale = payload.get("locale")
    messages = payload.get("messages")
    if not isinstance(locale, str) or not locale:
        raise RuntimeError(f"oldman-web-i18n 为 {source} 返回了无效 locale")
    if not isinstance(messages, dict):
        raise RuntimeError(f"oldman-web-i18n 为 {source} 返回了无效 messages")
    for message_id, value in messages.items():
        if not isinstance(message_id, str) or not isinstance(
            value,
            (str, list),
        ):
            raise RuntimeError(
                f"oldman-web-i18n 为 {source} 返回了无效消息"
            )
        if isinstance(value, list) and not all(
            isinstance(item, str) for item in value
        ):
            raise RuntimeError(
                f"oldman-web-i18n 为 {source} 返回了无效复数消息"
            )
    plural_rule = payload.get("pluralRule")
    if plural_rule is not None and not isinstance(plural_rule, str):
        raise RuntimeError(
            f"oldman-web-i18n 为 {source} 返回了无效 pluralRule"
        )
    return {
        "locale": locale,
        "messages": messages,
        **(
            {"pluralRule": plural_rule}
            if isinstance(plural_rule, str) and plural_rule
            else {}
        ),
    }


__all__ = [
    "build_frontend_i18n",
    "project_frontend_paths",
    "build_language_aliases",
    "catalog_filename",
    "read_i18n_contract",
    "validate_catalog_directory",
    "write_language_catalogs",
    "write_language_manifest",
    "write_language_manifest_data",
]
