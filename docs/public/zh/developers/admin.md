# 内置 Admin 与扩展

Admin 是 `oldman.apps.admin` App，依赖基础 Web、Auth 和 Session；浏览器端使用 `oldman-web` 的 Dashboard、Form、Table、Modal 和 Feedback。完整应用示例见[Admin 教程](../users/admin.md)。

## 入口与注册

```python
from oldman.apps.admin import AdminSite, AdminUserModelAdmin, ModelAdmin, install_admin, site
```

`site` 是包提供的默认站点。也可以创建 `AdminSite("project_admin")`，在一次服务初始化中注册后传给安装器；不要每个请求创建站点或重复安装路由。

| 方法 | 职责 |
| --- | --- |
| `AdminSite(name="oldman_admin", *, app_registry=None)` | 持有本管理站点的模型注册 |
| `register(model, admin_class=None)` | 返回 ModelAdmin；默认使用基类，重复注册同一模型报错 |
| `unregister(model)` | 移除已注册模型，不修改数据库 |
| `is_registered(model)` | 该模型是否已在这个站点注册 |
| `get_model_admin(model)` | 返回该模型的管理器 |
| `register_user_model(model)` | 保留唯一专用 User 管理器，由安装器正常调用 |
| `await menu_items(request, prefix="/admin")` / `await menu_groups(request, prefix="/admin")` | 从 Registry 展示元数据生成模型菜单及 App 分组，只列出这个请求能查看的模型 |

Registry 根据已安装 App 加载 models、views 和命令，不自动导入 `admin.py`。服务必须显式导入并注册业务 ModelAdmin。菜单只是不列出看不了的模型，访问仍由各路由自己检查。

## 安装器

签名中的类型可在编辑器中查看，调用形式为：

```python
install_admin(
    app,
    db_manager=None,
    admin_site=None,
    prefix="/admin",
    dev_mode=False,
    dev_server_url="",
    extension_bundle_name=None,
    auth_settings=None,
    admin_settings=None,
)
```

`prefix` 末尾的斜杠会被去掉，`/admin` 是首页的规范地址。Oldman Web 运行时以严格斜杠注册路由，Admin 因此额外把 `/admin/` 以 301 转到 `/admin` 并保留查询串；未开启严格斜杠的 Sanic 应用本来就两种写法都能命中，不会重复注册。

除 app 外均为关键字参数，返回安装后的 `AdminSite`。默认使用框架数据库管理器和默认 site；Auth/Admin 配置分别来自已注册 App 的强类型 settings。通常不需要逐个传这三项。

安装前提：

1. 服务 bootstrap 已完成，当前服务显式安装 Auth 与 Admin，业务模型已由 Registry 加载。
2. `WebApplication.init()` 已建立 Sanic、Session 等对象；`get_ext_config()` 启用了异步模板环境。
3. Session 配置启用，并有可访问的 Redis；正常使用前已执行数据库迁移。
4. 生产静态目录中存在已收集的 Admin manifest 和文件，或明确使用 Vite 开发模式。

安装器读取全局 `conf.settings.web.static` 和 SSE 配置；不读取 `app.ctx.settings`。从 `app.ctx.app_registry` 绑定已经存在的 Registry，不创建另一份。它注册选定的 User，接入模板和 CSRF，再添加站点路由。不会建表、自动迁移或创建默认管理员。

Admin Demo 同样不在启动钩子写数据：其25条项目在 `apps/demo/fixtures/demo.json`，由现有 `web loaddata demo` 显式导入。固定权限验收账号只在 `scripts/verify-admin-browser-with-servers.py` 的隔离数据准备阶段创建，不放进服务或fixture。普通账户使用 createsuperuser/changepassword，重启不重置密码或覆盖项目。fixture的重复导入/唯一约束/事务语义仍由[公共数据工具](fixtures.md)负责，没有Admin专用seed机制。

默认有 `/admin`、登录/注销、各模型列表和 CRUD、`/admin/user-session` 及修改当前密码/语言的共享入口。模型列表路径为 `/admin/<model_path>`，普通编辑路径为 `/admin/<model_path>/<object_id>/edit`。生成对象 URL 使用 `get_object_url()`，不要自行拼接特殊字符串主键。

通知 App 已安装时，Admin 安装共享通知 HTTP 路由及中心页面；SSE 是否启用单独控制用户事件路由。通知未安装时不安装持久通知中心及其业务接口，但共享顶栏仍保留操作活动下拉区域；这不表示已启用数据库通知。详情见[消息参考](messages.md)。

## ModelAdmin

`ModelAdmin(model, site=None)` 根据 SQLAlchemy 映射生成共享 Table/Form。内置 CRUD 要求单列主键；普通业务模型可用整数、字符串或 UUID 主键，Auth 的 User 则必须遵守固定整数主键合同。

常用类属性：

| 属性 | 默认与用途 |
| --- | --- |
| `list_display` | 空时取主键及普通列，总计最多五项，跳过 password_hash |
| `search_fields` | 空时使用可搜索的文本列，跳过 password_hash |
| `ordering` | 空时按主键；可用 `("-id",)` |
| `readonly_fields` | 不生成可编辑字段 |
| `exclude` | 从通用字段处理中排除的列 |
| `page_size` | 20 |
| `table_selectable` | false；不是自动提供批量操作业务 |
| `require_superuser` | false；为 true 时只有超级用户能进入该模型，角色给的权限对它不起作用 |
| `add_button_icon` | `ri-add-line`；自定义图标需进入应用 CSS 构建 |
| `form_card_classes` | `max-w-3xl` |
| `show_form_card_header` | true |

主要扩展点：

- `get_list_display()`、`get_search_fields()`、`get_ordering()`、`get_readonly_fields()`：返回字段序列。
- `get_table_columns()`：返回共享 Table 的列声明，默认来自 list_display。关系路径与排序规则参照 [Table](tables.md)，不是任意字符串都能变成数据库列。
- `get_form_class(*, create=True, dialect=None)`：返回 Form 类；自动实现使用 `TailwindModelForm`。覆盖时保持此签名，可以返回业务自己的 ModelForm。
- `build_form(request, *, instance=None, session=None)`：将请求、实例和当前事务传给表单。
- `async get_object(session, object_id)`：解析单列主键并读取实例；找不到返回 None，非法主键产生 `InvalidAdminObjectId`，由站点转成相应错误。
- `async save_model(session, instance)`：默认 add + flush，返回实例；不提交外层事务。
- `async delete_model(session, instance)`：默认 delete + flush；同样不自行提交。
- `async after_save(request, instance, *, created)`、`async after_delete(request, instance)`：新建、编辑、删除的事务**提交之后**才调用（用户管理里的启用/停用、修改密码也保存了用户这一行，同样调用 `after_save`，`created=False`），默认什么都不做。用来做只能跟在已提交的修改后面的事，比如刷新数据库之外的一份副本；这里抛出异常会让响应失败，但保存或删除已经生效；`after_save` 抛出 `ServiceUnavailable`（它依赖的存储不可用）时，Admin 的表单请求得到带 `error_code` 1503 的框架响应，界面能显示它翻译后的消息。
- `await has_view_permission(request, obj=None)`、`await has_add_permission(request)`、`await has_change_permission(request, obj=None)`、`await has_delete_permission(request, obj=None)`：异步布尔判断，默认各自检查该模型对应动作的权限（见下文「权限与 User」）。处理函数先不带对象检查一次，读出对象后再带着对象检查一次；需要按对象判断时重写这些方法，先 `await super()...` 再加自己的条件。
- `row_value(instance, field_name)`、`table_cell_value(instance, field_name, *, admin_prefix)`：定制展示值；可信 HTML 需要按共享 Table 的输出规则显式声明。默认实现把布尔值渲染成 Yes/No 徽章，`datetime` 显示为 `YYYY-MM-DD HH:MM` 并把 ISO 8601 作为 raw value，`date` 直接用 ISO 日期；其余值保持规范化后的原值。
- `table_action_html(instance, *, admin_prefix)`、`get_edit_extra_buttons(instance, admin_prefix)`：定制控制按钮；需复用共享 DOM 和 actions 协议。

保存钩子拿到的是当前请求事务。可以在里面设置业务字段，再 `await super().save_model(session, instance)`；不要另开一次提交，也不要在 flush 后就假定提交成功。文件字段仍遵循[模型文件生命周期](storage.md)，不由 Admin 单独删除附件。

显示名默认读取模型 Meta，可由 ModelAdmin 的 `verbose_name` / `verbose_name_plural` 属性覆盖。一级菜单使用 App 的 display_name 与 icon，二级使用模型名称。`model_path` 默认取数据库表名，改显示名不会改 URL 或表结构。

## 权限与 User

入口登录校验用户真实密码及 active/staff，之后请求使用强类型 Session 快照；不是每次渲染重新查 User。staff 只表示能登录后台，进入哪个模型、能做什么由[权限](permissions.md)决定：

- 每个注册的模型（User 模型除外，见下文）有四个权限：`admin.<App label>.<小写类名>.view`、`.add`、`.change`、`.delete`，例如 `admin.examples.exampleproject.view`，在 `AdminSite.register()` 时声明，所以服务一启动就能把它们放进角色。显示名带着模型名（如「查看 Articles」，模型名取 `verbose_name_plural`），角色编辑时所有模型的权限列在一起也分得清。`ModelAdmin.permission(action)` 返回其中一个。同一个模型注册到多个 AdminSite 时共用这四个权限。权限名用类名而不是表名：老数据库的表名（`LegacyOrders`、`2024_orders`）不一定合乎权限名的格式，类名小写后通常就合乎——以下划线开头或含非 ASCII 字母的类名除外，注册时报错，这时给模型类换个名字（表名和后台网址不变）；带上 App label 是因为不同 App 可以有同名的类（和 Django 的 `app_label.view_model` 一样）。模型不经过 App 加载时（测试、脚本）没有 App 这一段；App 的标签是服务加载模型时写到表上的，所以要在模型加载之后注册（服务 `init()` 里 `super().init()` 之后）。在那之前注册的模型声明的是不带 App 段的名字，而之后检查的是带 App 段的名字，`install_admin` 装路由时发现两者不一致就报错，不让服务带着一套永远通不过的权限启动；万一两个模型会得到同一个名字，注册第二个时报错，不会让它们共用权限。后台网址仍然用表名（`model_path`）。
- 超级用户持有全部权限。其他 staff 需要持有带着这些权限的角色：没有 view 看不到菜单项、打开列表回 403；没有 add 不显示新建按钮、新建页回 403；没有 delete 编辑页不显示删除按钮。表格每行的操作按钮不按权限隐藏，没有 change 或 delete 时点开对应页面或提交回 403。没安装 `oldman.apps.roles` 的服务里，只有超级用户能进入模型。
- 超级用户专用有两个开关：整个后台的 `app_settings.admin.require_superuser`（`AdminSettings`），和单个模型的 `ModelAdmin.require_superuser`。整个后台的开关在登录后台时、后台首页、「当前会话」页（含修改自己的密码）和每个模型页面上都检查，模型级的开关在该模型的页面上检查，所以与别的服务共用登录状态、没经过后台登录页进来的 staff 也进不了这些页面，登录页也不会把他当作已登录而跳走；改界面语言不受限制，未登录也能改；这时角色给的权限不起作用。模型级的开关让这个模型不声明四个权限，角色编辑页里不会出现；整个后台的开关在注册模型时还不知道，角色编辑页仍会列出这些权限，勾了也不起作用。

用户管理检查的是 auth App 自己声明的 `auth.users.view`、`.add`、`.change`、`.delete`（见[权限](permissions.md#auth-app-声明的权限)），不是 Admin 的模型权限：项目自己的用户管理页面检查的也是这四个，同一个角色在哪里管理用户都一样。在此之上，普通 staff 只能管理普通用户（既不是 staff 也不是超级用户的账号），不管他的角色给了什么权限。新建或编辑时勾选 staff/超级用户，或者编辑、删除、启停、修改一个 staff/超级用户账号的密码，都会得到「没有权限」；这些只有超级用户能做。给用户新加的角色，它授予的权限必须全在操作者自己持有的范围内（超级用户不受限制）；去掉角色、保留对方原有的角色不受限制。

### 角色管理

服务安装了 `oldman.apps.roles` 时，安装器把角色模型注册到 Admin（项目已经用自己的 ModelAdmin 注册了 `Role` 时保留项目的），菜单里出现「角色」。它的四个权限就是上面说的模型权限 `admin.roles.role.view/add/change/delete`。

- 新建和编辑用 `oldman.apps.roles.forms.RoleForm`：名称（唯一）、说明、权限。权限列出服务声明的全部权限，按声明它的 App 分组成复选框（组名是 App 的显示名）；保存时排序去重。不是超级用户的人编辑角色时，新勾上的权限必须是自己持有的；取消、保留原有的权限不受限制。角色里存着、但本服务没有声明的权限名（例如共用角色表的另一个服务声明的 `admin.*`），编辑页不显示，保存时原样保留：保存只改本服务声明的那些。代码已经不再声明的旧权限名从这里分辨不出来，也会保留。
- 保存的事务提交之后，`RoleModelAdmin` 用 `after_save` 把角色的权限写进它的缓存键；Redis 写失败时响应是 503，角色已经保存，Redis 恢复后再保存一次这个角色就修好了；这个 503 用框架的响应格式（`error_code` 1503），界面显示翻译后的「权限存储暂时不可用」，而不是笼统的「请求失败」。删除时先在事务里删掉缓存键、再删行，提交后用 `after_delete` 再删一次（见[权限](permissions.md#角色oldmanappsroles)）；Redis 不可用时第一步就失败，响应 503，什么都没删，Redis 恢复后再删即可。
- 能修改角色的人能给任何角色加任何权限，包括他自己持有的角色；框架不再加限制，这个权限只给信得过的人。
- 用户的新建和编辑表单多一组「角色」复选框（至少有一个角色时才出现），编辑页勾着用户现在持有的角色。保存时和用户行在同一个事务里写入；角色有变化时，提交后结束这个用户的全部登录，和改变启用/staff/超级用户标志一样。上面的规则照样适用：staff 和超级用户账号只有超级用户能编辑，所以也只有超级用户能给它们分配角色；能修改普通用户的 staff 可以给普通用户分配任何角色。

内置权限不提供租户级自动行过滤。需要按用户隔离数据、复杂流程或审批时，优先编写有明确查询条件的业务 Dashboard，而不是只隐藏 Admin 菜单。

`AdminUserModelAdmin` 提供 User 专用表单、密码和状态操作。希望扩展选定 User 的管理界面时，先用该类的子类注册，而不是普通 ModelAdmin；安装器会保留已经注册的专用管理器。自定义 User 的字段、真实外键和迁移归属见[数据库参考](database.md)。

`createsuperuser`、`changepassword` 是 Admin App 的异步命令；执行命令需要该服务安装 App，但不启动 Sanic。脚本和门禁用 `createsuperuser --noinput`：用户名（必须显式给 `--username`）和邮箱走参数，密码读环境变量 `OLDMAN_SUPERUSER_PASSWORD`（不放进命令行参数，避免进入进程列表和 shell 历史）。同名用户存在时两种模式都直接报错：`ensure_superuser` 会覆盖密码并把账号提成 active+staff+superuser，发布脚本重复执行会静默回滚管理员自己改过的密码，拿一个普通用户名执行则等于提权。确实要「有就更新」时显式加 `--update`。`change_user_password()` 本身只更新数据库密码；`changepassword` 与 `createsuperuser --update` 改完后调用 `end_user_logins(user_id)`，该用户已有的 Session 与访问令牌全部作废。Admin 里停用、删除用户，或保存时改变了启用/staff/超级用户标志，同样结束该用户的登录；只改资料（用户名、邮箱、显示名）不影响登录。

## 资源与模板

项目模板 loader 在前，共享模板和 Admin 模板作为后备。可在项目的模板目录提供 `admin/login.html`、`admin/index.html` 或实际使用的其他同名路径。覆盖者须保留所需布局、CSRF、Form message、bundle 和页面入口约定；不能只复制外观丢掉协议。

正常生产使用当前发行包内的 Admin 构建文件，运行本服务 `static collect`。`dev_mode=True` 时必须提供合法的 HTTP(S) `dev_server_url`，指向实际运行的 Admin Vite 服务；生产不可依赖开发服务器。

扩展 CSS 时，先向当前 `app.ctx.static_bundle_registry` 注册应用自己的 `StaticBundle`，再传 `extension_bundle_name="app:admin-style"`。该 bundle 的入口必须是 `.css`，且构建可用。默认 Admin 主入口仍为 `oldman:admin`，不能用第二套私有 JS 重写公共交互。

静态目录、全局 Settings、App Settings、bundle 和模板是不同对象；不要通过给 app.ctx 增加一份 Settings 解决缺配置或缺构建的问题。
