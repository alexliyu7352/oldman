# 运行并理解 Admin Demo

内置 Admin 的真实示例在独立的 [Oldman Admin Demo](https://github.com/alexliyu7352/oldman-admin-demo)。EPG Demo 的用户管理页是业务 Dashboard；不能因为 EPG 安装了 Admin App，就假定它已经提供自动生成的 /admin 站点。

本章使用 Admin Demo 自己的 `DemoProject` 和 `DemoProjectAdmin`，不把 EPG 的 ExampleProject 当成已经注册的 Admin 模型。两个仓库各有虚拟环境、配置和 SQLite 数据库。

## 1. 初始化与运行

命令均在 **Admin Demo 根目录**执行。先准备可用 Redis，默认 Session 使用本机 6379/5，SSE 使用 6379/6。检查 [example YAML](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/data/web_settings.example.yaml)，不要指向生产数据库。

首次运行：

```sh
python3 scripts/bootstrap.py
./run.sh web settings init
./run.sh web settings sync
./run.sh db migrate
./run.sh web loaddata demo
./run.sh web createsuperuser
pnpm --dir frontend build
./run.sh web static collect
./run.sh web start
```

init 读取 Demo 的 example YAML 创建本地配置；已有 web_settings.yaml 时跳过 init，不覆盖配置。数据库迁移按交互核对首次使用或现有状态。createsuperuser 通过隐藏输入创建你自己的账号，密码不放到命令参数或 Git。

打开 [http://127.0.0.1:17999/admin](http://127.0.0.1:17999/admin)，不是 EPG 的 17997。修改密码使用 `./run.sh web changepassword <用户名>`，将占位符替换为你实际创建的用户名。

bootstrap 的本地源码/发行包选择与 EPG 一致：同级存在 oldman_framwork 或 oldman 源码目录时直接关联源码，否则使用清单中的发行包。不要把两个 Demo 安装到框架自己的环境里。

`loaddata demo` 读取 [apps/demo/fixtures/demo.json](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/apps/demo/fixtures/demo.json)，显式导入25条真实项目记录，不创建任何用户。服务正常启动只初始化框架/站点，不自动导入数据、重置密码或删除用户；修改或删除项目后重启仍保留结果。已有项目、不需要预设数据时可以跳过导入，直接在后台创建自己的记录。

fixture 使用主键1–25，再次导入会按主键更新文件提供的字段，不是仅补缺失数据；已有同名不同主键会由唯一约束拒绝，整个文件回滚。只在自己的演示数据库执行，不能拿它覆盖业务记录。旧版本启动曾生成固定的 browser_staff、browser_superuser_guard 等测试账号；升级源码不擅自删除已有账号，请在自己的 Admin 中检查并禁用/删除不再需要的账号，不能把固定测试密码带入对外服务。现在只有隔离浏览器验证脚本创建这些测试账号。

## 2. 看实际模型与 ModelAdmin

模型位于 [apps/demo/models.py](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/apps/demo/models.py)，数据库表是 `admin_demo_project`，包含 name、owner、status、is_active、created_at。App 的 label 是 `demo`，显示名称和图标定义在 [apps/demo/apps.py](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/apps/demo/apps.py)。

[apps/demo/admin.py](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/apps/demo/admin.py) 的完整代码：

```python
"""Admin registrations for demo models."""

from oldman.apps.admin import ModelAdmin


class DemoProjectAdmin(ModelAdmin):
    """Admin presentation for demo projects."""

    require_superuser = True
    list_display = ("id", "name", "owner", "status", "is_active", "created_at")
    search_fields = ("name", "owner", "status")
    readonly_fields = ("created_at",)
    ordering = ("name",)
```

因此该模型要求 superuser；站点配置 `require_superuser: false` 只代表站点允许 active/staff 登录，不会取消模型自己的更严格限制。created_at 只读，默认按 name 排序。

一级菜单使用 App 的 display_name/icon，二级使用模型展示名称；修改显示文本不更改数据库表名和 URL 标识。

## 3. 注册 App 不等于安装站点

服务 YAML 已安装 oldman.auth、oldman.apps.admin、通知 App 和 apps.demo。模型进入 Registry 后，Admin 还需要显式站点接线。

在 [services/web.py](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/services/web.py) 的 WebService.init 中：

1. 执行 super().init()，取得已初始化的 runtime_app。
2. 导入 DemoProject、DemoProjectAdmin 和当前示例所用的默认 User。
3. 创建 AdminSite，注册 User 和 DemoProject。
4. 注册 Demo 自己的扩展 CSS bundle。
5. 调用 install_admin，将站点和扩展 bundle 交给框架。

其中模型注册的原文节选：

```python
        admin_site = AdminSite("oldman_admin_demo")
        admin_site.register(User, AdminUserModelAdmin)
        admin_site.register(DemoProject, DemoProjectAdmin)
```

同一方法中的站点安装原文：

```python
        install_admin(
            app,
            admin_site=admin_site,
            dev_mode=local_frontend,
            dev_server_url=(
                settings.web.frontend.vite_dev_server_url if local_frontend else ""
            ),
            extension_bundle_name=ADMIN_EXTENSION_BUNDLE,
            auth_settings=auth_app.settings,
            admin_settings=admin_app.settings,
        )
```

这不是独立片段：app 来自 runtime_app，local_frontend 是该 Demo 的源码调试开关，ADMIN_EXTENSION_BUNDLE 是服务模块的常量；StaticBundleRegistry 的完整构建仍在同一 init 方法。不要只复制最后一次调用而漏掉前面的资源注册。

框架和这个 Demo 都使用全局 settings 与 App 自己的强类型 settings，不在 app.ctx 复制配置；install_admin 的必要前置是已加载的服务/App配置与站点注册，不是另设一个 settings 对象。

install_admin 负责共享模板、CSRF、资源和路由接线。Admin App 安装、模型注册、站点安装是三个不同步骤；模型文件存在并不意味着自动授权出现在后台菜单。

## 4. 资源和源码调试

内置 Admin 的浏览器产物随 Python 包提供，业务使用它不必重写前端。这个 Demo 额外提供自己的样式 bundle，所以其 README 还要求构建 frontend。

产品模式读已构建 manifest；本地源码调试时，停止自己启动的产品模式服务，再运行：

```sh
python3 scripts/dev.py
```

该 Demo 脚本管理 Web 与两个 Vite 服务：内置 Admin 使用 5173，Demo 扩展使用 5174。它不改变 run.sh 的语义。资源加载失败时核对 [frontend 构建配置](https://github.com/alexliyu7352/oldman-admin-demo/tree/main/frontend)、静态收集和服务 bundle，不复制带 hash 的脚本地址到模板里。

## 5. 实际检查

使用自己创建的超级用户登录，操作一个自己的项目：

- 新建、搜索、编辑、重新打开，确认字段值真正保存；不要仅检查成功提示。
- 留空必填字段应失败，不新增行。
- 普通 staff 登录不等于可以访问 require_superuser 的 Project 管理；不要降低权限来让测试通过。
- 左侧应以 App 分组，模型处于二级菜单，而不是一个扁平 Models 列表。
- 删除自己的项目需确认；取消不改变记录。
- 注销后访问受保护页面应要求登录。
- 长时间放置页面后出现 CSRF 403，应刷新取得新令牌；不要关闭 CSRF。

需要自定义表单、列、保存规则或权限时看 [ModelAdmin 参考](../developers/admin.md#modeladmin)。项目模板通过 settings.web.template.dir 中的同名模板覆盖，不直接修改安装包资源。额外图标和 CSS 使用 extension bundle，不另建一套 Admin Form/Modal。

## 6. 找回密码

登录卡右下角的"忘记密码？"进入 `/admin/password-reset`。流程和 Django 一致：

1. 输入账号邮箱并提交。不管邮箱有没有账号，页面都跳到"请查收邮件"，不会泄露账号是否存在；账号存在且启用时，收件箱会收到一封带链接的邮件。
2. 打开邮件里的链接（`web.domain` 加上 `/admin/password-reset/<用户标识>/<token>`），设置新密码并确认，规则和后台改密码一样：8 到 128 位，字母和数字都要有。
3. 改完后该用户在其他浏览器里的登录会话全部失效，页面提示用新密码登录。

链接默认 24 小时内有效，改过密码、重新登录或过期后都会失效，同一个链接只能用一次。没有邮箱的账号不能自助找回，管理员在用户列表里改密码即可。每个 IP 15 分钟内最多申请 5 次（超出返回 429），每个邮箱 1 小时内最多收 3 封（超出后页面照常显示"已发送"但不再发信）。这些数值在 Auth App 的 `password_reset` 设置里，见[配置](../developers/configuration.md#app-settings)。

本地开发时邮件后端默认是 console，邮件连同链接会打印在服务日志里；真实发信要配置 `mail.backend` 为 smtp，见[邮件](../developers/mail.md)。

## 常见问题

| 现象 | 检查 |
| --- | --- |
| 没有 createsuperuser 命令 | 当前服务是否安装 oldman.apps.admin |
| App auth 未安装 | 当前 YAML 是否安装 oldman.auth，并完成 settings sync |
| 页面 404 | 是否运行正确 Demo/端口，服务是否调用 install_admin |
| 模型不在菜单 | 是否注册 ModelAdmin，当前用户是否满足模型权限 |
| 用户可登录但 Project 被拒绝 | DemoProjectAdmin.require_superuser 明确为 true |
| manifest 或图标缺失 | 是否完成产品资源构建/收集；扩展 bundle 是否存在 |
| 新数据库没有预设项目 | 先迁移，再显式执行 web loaddata demo；启动本身不会创建演示数据 |
| 导入发生名称冲突 | 核对已有同名记录与fixture主键；不清库、不自动按名称合并 |

部署前继续阅读[部署与运行](deployment.md)，但不能把“可以运行 Demo”当成已经完成生产安全配置。
