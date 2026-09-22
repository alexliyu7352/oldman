# {{ project_name }}

Oldman Dashboard 应用项目。默认服务是 {{ service_name }}，配置在 data/{{ service_name }}_settings.yaml。run.sh 只透传命令，不会替你创建数据、构建前端或启动全部服务。

## 首次运行

在本项目根目录安装 Python 依赖并补全配置：

```sh
uv sync
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} settings check
./run.sh db migrate
```

迁移是项目级命令，按交互提示执行当前 App 携带的迁移；不会启动 Web。生成项目预填 Auth 和 Admin App，以提供用户模型和账户命令，但不自动安装 /admin 站点，也没有默认登录账户。

新建业务页面：

```sh
./run.sh startapp reports
```

交互选择 dashboard 类型。命令生成 apps/reports、对应模板及 frontend/src/pages/reports.ts。检查 data/{{ service_name }}_settings.yaml 的 apps 包含 apps.reports，再运行 settings sync/check；已有 YAML 不会被命令随意覆盖。

生成的 /reports 是展示页，不是已经接好数据库、登录、持久通知的生产业务。先在本机验证，添加真实写操作前接入权限、CSRF、Form 与数据库；需要账户时使用：

```sh
./run.sh {{ service_name }} createsuperuser
./run.sh {{ service_name }} changepassword --help
```

启用 Session 时还需设置 web.session.enabled 和可访问的 redis.SESSION 连接。Session 和 Auth App 的存在不等于所有路由自动要求登录。

## 前端和启动

在 frontend 目录：

```sh
pnpm install
pnpm add -D sass
pnpm typecheck
pnpm build
```

Sass 供 Vite 编译组件 SCSS；pnpm 隔离依赖布局下，显式声明构建工具，不依赖间接依赖提升。生成的 oldman-web 依赖要求所用索引有对应版本；本地源码开发可在应用中关联已有 dist 的包目录，不复制框架源码。

回到项目根：

```sh
./run.sh {{ service_name }} start
```

按启动日志的地址打开 /reports，不要默认访问尚未注册的 /。监听地址和端口来自服务 YAML。Ctrl+C 停止服务。修改前端后重新 pnpm build；生产模式读取 static/dist/.vite/manifest.json，不直接执行 src。

开发模式用两个终端分别运行：

```sh
# 终端一，在 frontend：
pnpm dev
# 终端二，在项目根：
./run.sh {{ service_name }} dev
```

Vite 地址由 web.frontend.vite_dev_server_url 配置。dev 是显式命令，不改变 run.sh 语义。

## 文件分工

- services/{{ service_name }}.py：Web、模板和 Vite bundle 接线。
- apps/<app>/apps.py：App 元数据；models、views、commands 由 Registry 按阶段加载。
- templates/base.html：共用 Dashboard 壳；templates/errors 可覆盖错误页。
- frontend/src/main.ts：i18n、运行时和页面 loader；pages 中注册 DashboardPage。
- data/{{ service_name }}_settings.yaml：本服务配置；密钥、数据库、日志和虚拟环境不是示例源码。

每个页面的 page_entry、页面文件及 setupPage 名称必须一致。只需 HTML 的页面也要使用能够挂载其组件的 Page。Modal 中使用普通 Form，不另写表单专用 Modal。

## 图标、样式和翻译

pnpm 的 prebuild/predev/pretypecheck 自动生成项目图标；前两个还生成翻译 JSON。样式扫描 templates、业务 TypeScript 和 apps 中的 Python。完整图标名使用 ri-*、mdi-* 或 bx-*，不要用未进入扫描源的动态拼接名。

在项目根维护统一翻译：

生成的 babel.cfg 已包含 Jinja、i18n 与 CSRF 的提取扩展，无需另行安装提取插件。修改模板语法时不要通过删除 CSRF 扩展或 silent=True 掩盖解析失败。

```sh
./run.sh i18n extract
./run.sh i18n init zh-Hans
./run.sh i18n init zh-Hant
./run.sh i18n update
# 编辑 locales/<locale>/LC_MESSAGES/messages.po 后：
./run.sh i18n compile
```

已有语言不重复 init。Python、Jinja、App 命令及前端共用 messages；MO 和浏览器 JSON 是不同产物，不另维护前端 PO。App 命令 help 用 lazy translation。`./run.sh i18n compile-frontend --service {{ service_name }}`（`pnpm generate:i18n` 会调它）读取本服务语言设置，只编译浏览器需要的词条，写出 `frontend/public/i18n/<code>.json` 和前端导入的 `frontend/src/i18n/generated.ts`；语言集合进了构建产物，所以新增语言后必须重新构建前端。

## 下一步

参阅 Oldman 的 [Dashboard 教程](https://github.com/alexliyu7352/oldman/blob/master/docs/users/tutorial-dashboard.md)、[Form/Table 与浏览器参考](https://github.com/alexliyu7352/oldman/blob/master/docs/developers/README.md)和 [Agent CRUD 指南](https://github.com/alexliyu7352/oldman/blob/master/docs/agents/dashboard-crud.md)。安装旧版本时，应选择与其匹配的文档版本。

项目自行定义数据访问范围、部署配置和业务行为；不要把脚手架展示记录当真实数据或完整业务验收。
