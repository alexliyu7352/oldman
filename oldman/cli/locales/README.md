# 框架 CLI 翻译维护

CLI 使用统一的 gettext `messages` domain，不使用独立 cli domain。本目录是框架 CLI 的后备词典；运行项目时，项目与已安装 App 的 messages 参与合并，项目覆盖优先。语言选择及 App 命令见[CLI 参考](../../../docs/developers/cli.md)，全链路见[资源与翻译](../../../docs/developers/assets.md)。

`oldman/cli/babel.cfg` 的输入根是 `oldman/`，只提取 `cli/**/*.py` 和 `runtime/base.py`。后者提供默认服务命令描述。Typer 自己产生的帮助文案通过 CLI 中显式可提取词条纳入，不扫描第三方包源码。

框架 Admin 和 notifications 的词典位于各自 App 的 locales，不因 domain 相同就要求所有 PO 放在同一个目录。项目 `oldman i18n extract` 才会把项目、已安装 App 和框架来源组织成应用的统一 POT；前端 JSON 又按实际前端词条过滤，不把全部后端词条传给浏览器。

在**框架根目录**运行：

```sh
.venv/bin/pybabel extract -F oldman/cli/babel.cfg \
  -k _ -k gettext -k gettext_noop -k ngettext:1,2 \
  -o oldman/cli/locales/messages.pot oldman
.venv/bin/pybabel update -D messages \
  -i oldman/cli/locales/messages.pot -d oldman/cli/locales -l zh_Hans
.venv/bin/pybabel update -D messages \
  -i oldman/cli/locales/messages.pot -d oldman/cli/locales -l zh_Hant
```

之后人工编辑两份 PO：补齐有效空词条，核对插值和复数，把已经确认的 fuzzy 译文转成正式翻译。不能只跑 compile 就声称翻译完整。

```sh
.venv/bin/pybabel compile -D messages -d oldman/cli/locales
```

最后使用实际英文、简体和繁体 CLI 帮助，检查命令分组、参数帮助、交互取消及一条错误路径。PO 目录采用 Babel 的 `zh_Hans`/`zh_Hant`，CLI 语言码使用 `zh-Hans`/`zh-Hant`；不要凭文件名猜命令参数。

上述命令会修改翻译产物；按本次任务审阅并提交，不替换用户正在编辑的词典。wheel 使用编译后的 MO，因此只修改 PO 不足以让安装包显示新译文。
