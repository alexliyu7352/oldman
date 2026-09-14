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
| `get_model_admin(model)` | 返回该模型的管理器 |
| `register_user_model(model)` | 保留唯一专用 User 管理器，由安装器正常调用 |
| `menu_items(prefix="/admin")` / `menu_groups(prefix="/admin")` | 从 Registry 展示元数据生成模型菜单及 App 分组 |

Registry 根据已安装 App 加载 models、views 和命令，不自动导入 `admin.py`。服务必须显式导入并注册业务 ModelAdmin。菜单不等于权限判定，访问仍由各路由的权限检查决定。

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

除 app 外均为关键字参数，返回安装后的 `AdminSite`。默认使用框架数据库管理器和默认 site；Auth/Admin 配置分别来自已注册 App 的强类型 settings。通常不需要逐个传这三项。

安装前提：

1. 服务 bootstrap 已完成，当前服务显式安装 Auth 与 Admin，业务模型已由 Registry 加载。
2. `WebApplication.init()` 已建立 Sanic、Session 等对象；`get_ext_config()` 启用了异步模板环境。
3. Session 配置启用，并有可访问的 Redis；正常使用前已执行数据库迁移。
4. 生产静态目录中存在已收集的 Admin manifest 和文件，或明确使用 Vite 开发模式。

安装器读取全局 `conf.settings.web.static` 和 SSE 配置；不读取 `app.ctx.settings`。从 `app.ctx.oldman_app_registry` 绑定已经存在的 Registry，不创建另一份。它注册选定的 User，接入模板和 CSRF，再添加站点路由。不会建表、自动迁移或创建默认管理员。

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
| `require_superuser` | false；该模型可进一步收紧站点权限 |
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
- `has_view_permission(request)`、`has_add_permission(request)`、`has_change_permission(request)`、`has_delete_permission(request)`：同步布尔判断；默认后面三个沿用 view 权限。
- `row_value(instance, field_name)`、`table_cell_value(instance, field_name, *, admin_prefix)`：定制展示值；可信 HTML 需要按共享 Table 的输出规则显式声明。
- `table_action_html(instance, *, admin_prefix)`、`get_edit_extra_buttons(instance, admin_prefix)`：定制控制按钮；需复用共享 DOM 和 actions 协议。

保存钩子拿到的是当前请求事务。可以在里面设置业务字段，再 `await super().save_model(session, instance)`；不要另开一次提交，也不要在 flush 后就假定提交成功。文件字段仍遵循[模型文件生命周期](storage.md)，不由 Admin 单独删除附件。

显示名默认读取模型 Meta，可由 ModelAdmin 的 `verbose_name` / `verbose_name_plural` 属性覆盖。一级菜单使用 App 的 display_name 与 icon，二级使用模型名称。`model_path` 默认取数据库表名，改显示名不会改 URL 或表结构。

## 权限与 User

入口登录校验用户真实密码及 active/staff，之后请求使用强类型 Session 快照；不是每次渲染重新查 User。站点或模型的 `require_superuser` 可再要求超级用户。

内置权限不提供租户级自动行过滤。需要按用户隔离数据、复杂流程或审批时，优先编写有明确查询条件的业务 Dashboard，而不是只隐藏 Admin 菜单。

`AdminUserModelAdmin` 提供 User 专用表单、密码和状态操作。希望扩展选定 User 的管理界面时，先用该类的子类注册，而不是普通 ModelAdmin；安装器会保留已经注册的专用管理器。自定义 User 的字段、真实外键和迁移归属见[数据库参考](database.md)。

`createsuperuser`、`changepassword` 是 Admin App 的异步命令；执行命令需要该服务安装 App，但不启动 Sanic。当前 `change_user_password()` 只更新数据库密码，不自动撤销既有 Session；不能把改密命令当作全端踢出。需要撤销登录时明确使用 [Session API](web.md#session-和认证不是自动登录系统)。

## 资源与模板

项目模板 loader 在前，共享模板和 Admin 模板作为后备。可在项目的模板目录提供 `admin/login.html`、`admin/index.html` 或实际使用的其他同名路径。覆盖者须保留所需布局、CSRF、Form message、bundle 和页面入口约定；不能只复制外观丢掉协议。

正常生产使用当前发行包内的 Admin 构建文件，运行本服务 `static collect`。`dev_mode=True` 时必须提供合法的 HTTP(S) `dev_server_url`，指向实际运行的 Admin Vite 服务；生产不可依赖开发服务器。

扩展 CSS 时，先向当前 `app.ctx.static_bundle_registry` 注册应用自己的 `StaticBundle`，再传 `extension_bundle_name="app:admin-style"`。该 bundle 的入口必须是 `.css`，且构建可用。默认 Admin 主入口仍为 `oldman:admin`，不能用第二套私有 JS 重写公共交互。

静态目录、全局 Settings、App Settings、bundle 和模板是不同对象；不要通过给 app.ctx 增加一份 Settings 解决缺配置或缺构建的问题。
