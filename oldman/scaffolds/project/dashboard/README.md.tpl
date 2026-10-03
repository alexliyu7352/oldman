# {{ project_name }}

Oldman Dashboard 项目。默认服务是 {{ service_name }}，配置在 data/{{ service_name }}_settings.yaml。run.sh 只透传命令，不会替你创建数据、构建前端或启动全部服务。

生成后就是一个能登录的后台：登录与登出、首页、个人页（语言、修改自己的密码）、通知、用户管理。所有启用的账户都能登录；用户管理要 `auth.users.view` 等权限（超级用户都有，其他人经角色授予）。

## 首次运行

需要一个可用的 Redis：登录状态存在 Session 里，Session 用配置 `redis.SESSION` 那个连接（默认 `localhost:6379` 的 5 号库）。

在项目根目录：

```sh
uv sync
./run.sh {{ service_name }} settings sync
./run.sh {{ service_name }} settings check
./run.sh db migrate                         # 要在终端里回答迁移问题
./run.sh {{ service_name }} createsuperuser # 要在终端里输入账号和密码
```

`.python-version` 指定 Python 3.13（框架推荐的版本），`uv sync` 按它选解释器，本机没有时 uv 会自动下载；要用其他受支持的版本（3.12–3.14）就改这个文件。

在 frontend 目录：

```sh
pnpm install
pnpm build
```

回到项目根，把框架的静态文件（含内置 Admin 的前端，如果装了）收集到 `static/`，再启动；打开启动日志里的地址，会先到登录页：

```sh
./run.sh {{ service_name }} static collect
./run.sh {{ service_name }} start
```

升级框架后重新 `static collect`。

监听地址和端口来自服务 YAML。Ctrl+C 停止。生产模式读取 static/dist/.vite/manifest.json，修改前端后重新 `pnpm build`。开发时用两个终端：frontend 里 `pnpm dev`，项目根 `./run.sh {{ service_name }} dev`。

## 文件分工

- `apps/accounts/models.py`：项目自己的 User 模型（表仍是框架的 `oldman_user`）。要给用户加字段就在这里加，再 `./run.sh db makemigrations` 和 `./run.sh db migrate`。
- `apps/accounts/routes.py`：按配置 `web.account` 装登录、个人页与通知、用户管理三个框架流程。只让部分账户登录就给 `LoginFlow` 传 `accept_user`；要找回密码就在旁边装 `PasswordResetFlow`。
- `apps/home/`、`templates/home/index.html`：首页，换成自己的内容。
- `templates/base.html`：所有页面的外壳（侧栏、顶栏、语言、账户菜单），框架的账户页面也用它。
- `templates/partials/sidebar.html`：菜单只在这里列。新页面在这里加一项。
- `services/{{ service_name }}.py`：Web 服务的接线：CSRF、通知、模板与前端包、账户页面{{ readme_admin_wiring }}。
- `frontend/src/main.ts`：前端入口；`frontend/src/pages/base-page.ts` 是所有页面共用的页面类。
- `data/{{ service_name }}_settings.yaml`：本服务配置，含密钥，不进 Git。

登录、个人页、用户管理等页面的模板在框架里（`oldman/dashboard/account/*`）。要改哪一页，就在 `templates/` 下放同路径的文件，项目的优先；删掉就回到框架的版本。地址（`/login`、`/users` 等）在配置 `web.account` 里改。

## 新增页面

```sh
./run.sh startapp reports
```

选 dashboard 类型。命令生成 apps/reports、对应模板及 frontend/src/pages/reports.ts；把 `apps.reports` 加进服务 YAML 的 `apps`，在 `templates/partials/sidebar.html` 加一项链接，再 `settings sync`。生成的页面默认要求登录；要按权限放行，用 `require_perm` 或 `staff_required`（见框架文档的权限一节）。写操作要有 CSRF、Form 与数据库，不要把示例页当成已经完成的业务。

## 图标、样式和翻译

pnpm 的 prebuild/predev/pretypecheck 自动生成项目图标；前两个还生成浏览器语言包。样式扫描 templates、业务 TypeScript 和 apps 中的 Python。完整图标名使用 ri-*、mdi-* 或 bx-*，不要用未进入扫描源的动态拼接名。

语言按配置 `i18n` 走：`use_i18n` 打开多语言，`default_language` 是默认语言，`languages` 列出可选的语言；多于一种时顶栏出现语言切换。框架自带简体、繁体中文的翻译，开启后框架的页面直接是中文，项目只需翻译自己的文案：

```sh
./run.sh i18n extract
./run.sh i18n init zh-Hans
./run.sh i18n update
# 编辑 locales/<locale>/LC_MESSAGES/messages.po 后：
./run.sh i18n compile
```

已有语言不重复 init。新增语言后要重新 `pnpm build`：语言集合随前端构建一起发布。

## 下一步

参阅 Oldman 的 [Dashboard 教程](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/users/tutorial-dashboard.md)、[Form/Table 与浏览器参考](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/README.md)和 [Agent CRUD 指南](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/dashboard-crud.md)。安装旧版本时，应选择与其匹配的文档版本。
