# 权限

权限是"一个角色可以做什么"。某段代码要检查它，它才存在，所以它和那段代码一起在代码里声明、随代码发布；声明只定义有哪些权限，不授予任何人。

## 声明

App 在自己包里的 `permissions.py` 声明：

```python
from oldman.auth import Permission, PermissionSet
from oldman.i18n import gettext_lazy as _


class ReportPermissions(PermissionSet, namespace="reports"):
    view = Permission(_("View reports"))
    export = Permission(_("Export reports"))
```

- 名字是 `<命名空间>.<属性名>`，例如 `reports.export`。命名空间写声明它的 App 的 label；Web 服务启动时检查每个命名空间都属于某个已安装的 App，拼错或写了不存在的 App 会直接报错。
- 权限名按业务起，不和模型挂钩。
- 同一个名字只能声明一次，重复声明在导入时报错；一个 `Permission` 对象也只能属于一个 `PermissionSet`。
- 代码里引用声明出来的对象（`ReportPermissions.export`），不写字符串：拼错了在导入时就报错。
- 按名字批量生成权限的代码用 `declare_permission(namespace, codename, label)`，codename 可以用点分段，例如 `project.change`。

## 加载

`AppConfig.permissions_module` 默认是 `permissions`。每种服务（Web、常驻服务、命令行、Worker）在 `bootstrap_service()` 加载模型之后紧接着导入每个已安装 App 的这个模块（没有就跳过），所以视图导入时、命令行里批量建角色时，整个权限目录都已经存在。Admin 的模型权限不在这里声明，而是在注册模型时声明，只有注册了模型的服务里才有。和视图模块一样，导入它不能注册新的数据库模型。已有项目里叫 `permissions`、但另有用途的模块（比如放权限检查函数）也会在每种服务启动时被导入；不想这样，就在 App 的 `AppConfig` 里把 `permissions_module` 设成另一个名字——对应的模块不存在时直接跳过。

auth App 自己的权限模块叫 `user_permissions`（见下一节），因为 `oldman.auth.permissions` 是每个服务都会导入的声明机制，在那里声明会波及没安装 auth App 的服务。

`declared_permissions()` 按名字排序返回全部已声明的权限，`get_permission(name)` 按名字取一个；`Permission` 上有 `name`、`namespace`、`codename` 和 `label`。

## auth App 声明的权限

安装了 `oldman.auth` 的服务有四个管理用户的权限，在 `oldman.auth.user_permissions` 里：

| 对象 | 名字 |
| --- | --- |
| `VIEW_USERS` | `auth.users.view` |
| `ADD_USERS` | `auth.users.add` |
| `CHANGE_USERS` | `auth.users.change` |
| `DELETE_USERS` | `auth.users.delete` |

内置 Admin 的用户管理检查它们；项目自己写的用户管理页面也检查它们（`await require_perm(request, user_permissions.CHANGE_USERS)`），同一个角色在哪里管理用户都一样。`oldman.auth` 包本身不导入这个模块，没装 auth App 的服务没有这四个名字。

## 角色（`oldman.apps.roles`）

权限落在角色上：角色是一组权限名，用户持有角色；不支持给单个用户直接授权。角色和"谁持有哪些角色"是数据，存在数据库里，运行时维护。

安装：服务的 `apps` 加入 `oldman.apps.roles`，然后按[数据库迁移](migrations.md)执行 migrate。它是单独的 App、不在 `oldman.auth` 里，因为使用自定义 User 模型的项目不会加载 `oldman.auth` 的模型。

两张表：

- `oldman_role`：`id`、`name`（唯一）、`description`、`permissions`（权限名的 JSON 数组）。已删除角色的 id 不会再分配给新角色。
- `oldman_user_role`：`user_id`（外键指向 `oldman_user.id`）和 `role_id`，删除用户或角色时随之删除。

数据库是唯一的准，每个角色的权限另在 Redis 里存一份，键是 `<core.namespace>:role:<id>`，用的是 session 所在的安全存储连接。`oldman.apps.roles.store` 提供：

| 函数 | 作用 |
| --- | --- |
| `checked_permission_names(names)` | 排序去重；有未声明的权限名就报错。保存角色前用它校验 |
| `publish_role(role)` | 保存角色并提交之后调用，把权限写进它的键。写失败会抛出，重新保存即可修复 |
| `forget_role(role_id)` | 删掉角色的键。删除角色时调用两次：删行之前在同一个事务里调一次，Redis 拒绝就让异常回滚事务，什么都不删；提交之后再调一次，删掉删除前刚读到这个角色的请求写回的键。之后查这个 id 得不到任何权限 |
| `role_permissions(role_ids)` | 一次 MGET 取多个角色的权限并集。缺失的键从数据库读出，只在仍然缺失时写回，所以不会盖掉一次保存刚写入的新值 |
| `user_role_ids(user_id)` | 用户持有的角色 id，升序 |
| `replace_user_roles(session, user_id, role_ids)` | 在调用方的事务里把用户的角色换成给定的这些，返回是否有变化 |

内置 Admin 在服务安装了 roles App 时自带角色管理（见 [Admin](admin.md#角色管理)）。项目自己写角色管理页面时，表单用 `oldman.apps.roles.forms.RoleForm`（名称、说明、按 App 分组的权限复选框），保存的事务提交之后调用 `publish_role`；删除时按上表在删行之前和提交之后各调用一次 `forget_role`。`oldman.web.auth.roles_installed(app)` 回答服务装没装 roles App。

给用户分配角色用共用的用户表单（`oldman.web.auth.user_create_form_class` / `user_edit_form_class`）：服务装了 roles App、并且至少有一个角色时，表单带一组「角色」复选框，选项从数据库读，所以表单要绑定 session。用户行写入之后、在同一个事务里调用 `await form.save_roles(session, user)`（新用户这时才有 id），它返回角色是否有变化；返回 `True` 时在提交之后结束这个用户的登录。表单没有角色字段时它什么都不写，返回 `False`。

`publish_role` 和 `forget_role` 只有保存、删除角色的代码会调用。用 `loaddata` 导入角色、或直接改表时不经过它们：缓存里还没有这个角色的键时，下一次检查从数据库读到的就是新值；已经有键时，键里的旧权限会一直留着，要在 Admin 里把这个角色再保存一次（或删掉它的键）。

已知限制：某个请求在角色被删除前刚从数据库读到它、又在删除之后才写回键时，这个键会重新出现；它只影响仍带着这个 id 的登录，其他角色不受影响。这需要"键恰好缺失"和"删除"同时发生。

## 检查

```python
from oldman.web.auth import has_perm, require_perm
from oldman.web.components.tables import SQLAlchemyTableView

from apps.reports.permissions import ReportPermissions


async def export_report(request):
    await require_perm(request, ReportPermissions.export)   # 不持有就 403
    ...


class ReportTable(SQLAlchemyTableView):
    async def check_permission(self, request, *, method_name, route_kwargs):
        return await has_perm(request, ReportPermissions.view), None   # 不持有就 403,不查报表数据
```

- 超级用户持有全部权限，不做任何查询；未登录一律没有。其他用户持有的，是他登录时所持角色授予的权限。
- 角色 id 随登录一起走：登录时（服务安装了 `oldman.apps.roles`）写进 session 快照，取令牌和刷新令牌时写进访问令牌的 `roles` 声明，`request.ctx.user.role_ids` 读得到。没有安装 roles App 的服务，登录不带角色，只有超级用户能通过检查；与装了 roles App 的服务共用登录状态时，session 里带来的角色 id 在这里也不起作用，也不会去读角色缓存和角色表。
- 一个请求里第一次检查时按这些角色 id 从角色缓存取一次权限集合，之后的检查都读这份结果。缓存里没有的角色从数据库读，默认是进程的 `db_manager`；角色表在别的库里时（比如 Admin 装在自己的 `DatabaseManager` 上），`has_perm`、`require_perm`、`permissions_not_held` 都可以传 `db_manager=`，内置 Admin 传的就是它自己的。角色缓存所在的 Redis 不可用时回 503，不按"没有权限"处理。
- 检查只接受声明出来的 `Permission` 对象，传字符串会报错。
- 在哪里检查由业务决定：视图里调用 `require_perm`；表格、图表、下拉按下一节的分层放在对应的钩子里。框架不在组件上另加声明式属性，模板也不做权限判断：没有权限的内容由后端决定不渲染，或在操作时报错。
- 交出权限时只能交出自己持有的：`await permissions_not_held(request, names)` 返回这些权限名里当前用户没有持有的（排好序；超级用户永远是空列表）。共用的用户表单给用户**新加**角色、`RoleForm` 给角色**新加**权限时都用它：不是超级用户的人，新加的角色的全部权限、新加的权限都必须在自己持有的范围内，否则表单报错；去掉、保留原有的不受限制。否则能编辑角色或用户的人，就能给自己持有的角色、或自己掌握的账号，授予比自己更多的权限。项目自己写的授权页面也应当这样检查。
- 修改一个角色包含的权限立即对持有它的人生效，不需要重新登录。修改某个用户持有哪些角色（`replace_user_roles` 返回 `True`）时，调用方在提交后结束这个用户的登录（`revoke_user_logins` 或 `end_user_logins`）：他的 session 和令牌里还带着旧的角色 id。删除角色不结束任何人的登录，仍带着它的 id 的登录从它那里得不到任何权限。这依赖角色 id 不复用：SQLite 用 `AUTOINCREMENT`，PostgreSQL、MySQL 8.0 起的自增值也不回退；MySQL 5.7 及更早例外，它的自增计数只在内存里，数据库重启后从现有最大 id 接着往下发，删掉的最大 id 会被新角色重新用上。在这类数据库上删除角色前，先从 `UserRole`（`oldman_user_role` 表）查出持有它的用户，删除后对他们调用 `end_user_logins(user_id)`，让带着这个 id 的登录全部结束。
- 完整 Demo 的示例：[apps/examples/permissions.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/permissions.py) 声明 `examples.view_projects`，[apps/examples/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py) 里项目表格的 `check_permission` 检查它：登录用户都能打开页面，没有带这个权限的角色时表格数据回 403。Demo 的用户管理页按 `auth.users.*` 检查。fixture 带两个示例角色：授予 `examples.view_projects` 的 Project viewers、授予 `auth.users.*` 的 User managers，用户编辑页勾上即可。
- 内置 Admin 也用这套检查决定 staff 能进哪个模型、能做什么；每个模型自动声明的四个权限见 [Admin](admin.md#权限与-user)。

## 数据组件的权限分层

表格、图表、下拉的数据接口按顺序过四层,每层回答一个问题,拿得到的东西也不同:

| 层 | 何时执行 | 拿得到 | 回答的问题 | 拒绝时 |
| --- | --- | --- | --- | --- |
| `require_authenticated`(开关,组件默认 True) | 最先 | request | 登录了吗 | 未登录协议:401,页面请求跳登录页 |
| `check_permission(request, *, method_name, route_kwargs)` | 解析参数、打开数据库会话之前 | 用户、请求方法、路径参数 | 不查数据就能判断的整体拒绝:staff、角色权限、路由参数 | 403 |
| `check_auth(table_request)` / `check_auth(chart_request)` | 参数解析(图表还要校验)之后,SQLAlchemy 组件的只读会话已打开 | 解析后的请求:用户(`.request`)、路径参数、筛选、搜索;可以查库 | 要看参数或查库才能判断的整体拒绝 | 403 |
| 数据范围:表格 `apply_base_filters(query, table_request)`、下拉 `get_queryset(request, context)`、图表 `get_result(chart_request)` | 构造查询时 | 用户、路径参数、查询参数,以及查询本身 | 能看到哪些行 | 不拒绝,只缩小结果 |

下面是完整 Demo 的 Access Guards 页(`/examples/auth/guards`)上能运行的例子:[apps/examples/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py)
的 `TeamProjectTable` 继承示例项目表格,三个钩子各答一个问题。页面列出四种请求(匿名、非 staff、staff 选停用团队、staff 选启用团队)
各由哪个钩子回答,并显示这个类的源码。

```python
class TeamProjectTable(ExampleProjectTable):
    """One team's projects, read-only: how a data endpoint decides who gets what, one hook per question.

    The Access Guards example page mounts it. Each hook answers at its own moment:

    - ``check_permission`` — before the parameters are parsed or a session is opened: staff only. It
      replaces the parent's role check; a subclass states its own rule.
    - ``check_auth`` — after the parameters, with the read session open: the team in the path must
      exist and be active, which only the database knows. It can refuse the whole request, nothing less.
    - ``apply_base_filters`` — which rows: this team's projects. It refuses nothing; totals, pages and
      search all count within it.
    """

    route_name = "example_team_projects_table"
    route_path = "/examples/auth/teams/<team_id:int>/projects/table"
    selectable = False
    export_formats = ()
    empty_message = _("This team has no projects.")
    # Read-only: no team column (it is the one in the path) and no edit or delete buttons.
    columns = tuple(
        column for column in ExampleProjectTable.columns if isinstance(column, Column) and column.name not in {"team", "action"}
    )

    async def check_permission(self, request, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]:
        """Staff only, decided from the signed-in user alone."""
        del method_name, route_kwargs
        return request_user(request).is_staff, None

    async def check_auth(self, table_request) -> bool:
        """The team in the path must exist and be active."""
        team = await self.require_db_session().get(ExampleTeam, table_request.route_kwargs["team_id"])
        return team is not None and team.is_active

    async def apply_base_filters(self, query, table_request):
        """Only this team's projects."""
        return query.where(ExampleProject.team_id == table_request.route_kwargs["team_id"])
```

要按用户限定行(例如普通成员只看自己负责的项目)也写在 `apply_base_filters`:它决定的行同时是总数、分页和导出的范围。
不要放进 `check_auth`,它只能拒绝整个请求,改不了参与计数、分页、导出的那条查询。
下拉只有一个中心接口服务所有 provider,分派阶段还不知道是哪个 provider,单个 provider 的规则写在它自己的 `check_auth(request, context)`。
框架的 `UserTable` 自己在 `check_permission` 里要求 `auth.users.view`;内置 Admin 的表格把"staff(要求超级用户时是超级用户)+ 模型权限"写在
`check_permission`,经同一套分派调用。
