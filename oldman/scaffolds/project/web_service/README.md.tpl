# {{ project_name }}

基于 Oldman 的服务端 HTML 项目。服务入口是 `services/{{ service_name }}.py`，使用异步 Jinja 模板；配置位于 `data/{{ service_name }}_settings.yaml`。

## 开始运行

在项目根目录执行：

```sh
uv sync
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} settings check
./run.sh startapp pages
```

`startapp` 交互选择 `web`，填写显示名称。把 `apps.pages` 加入当前服务 YAML 的 `apps` 列表，再执行：

```sh
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} static collect
./run.sh {{ service_name }} start
```

访问 `http://127.0.0.1:17998/pages`。测试前将 YAML 的 `web.listen_host` 改成 `127.0.0.1`；更换端口时也更换访问 URL。根 `/` 没有自动生成页面。

`run.sh` 只执行本项目 `.venv/bin/oldman`，不自动生成数据或启动其他服务。Ctrl+C 停止，或另开终端执行 `./run.sh {{ service_name }} stop`。

## 配置和模板

脚手架已创建 YAML，`settings sync` 补齐默认字段和密钥；配置不存在时才使用 `settings init`。不要把真实密码和密钥提交到公开仓库。

模板放在 `templates/`；生成 App 的页面模板位于 `templates/pages/index.html`，views 位于 `apps/pages/views.py`。业务模型声明放在 App 的 `models.py`，不要放在 views 中。

使用数据库时，填写 `database.url` 并注册模型 App，再分别运行 `./run.sh db makemigrations` 和 `./run.sh db migrate`。服务启动不自动建表。没有数据库业务时不需要迁移。

## 依赖来源与翻译

`uv sync` 使用项目声明的发行包。当前版本尚未发布或需要源码调试时，参照 [源码安装说明](https://github.com/alexliyu7352/oldman/blob/master/docs/agents/create-service.md#新项目使用本地-python-源码)，使用本项目独立的 editable 环境。

在项目根运行 `./run.sh i18n extract`、`./run.sh i18n init <locale>`、`./run.sh i18n update`、`./run.sh i18n compile` 管理翻译。仅创建模板不会自动开启 Web 多语言，相关设置在 YAML 的 `i18n` 节点。
