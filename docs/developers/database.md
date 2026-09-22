# 模型与数据库会话

Oldman 使用 SQLAlchemy 映射和异步数据库驱动，不另造查询语言。声明模型、生成数据库结构、执行请求事务是三件事；首次使用见[Demo 真实数据教程](../users/tutorial-tasks.md)，结构变更见[迁移参考](migrations.md)。

本章从 EPG Demo 的 ExampleTeam/ExampleProject 和实时图表取例。所有代码都在该 Demo 已注册的 App 中运行；首次先按教程执行迁移、导入 fixture、创建账户，不能仅导入一个类就假定数据库结构已存在。

## 模型从哪里加载

[apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) 中 ExampleTeam 的完整声明如下。该文件启用 `from __future__ import annotations`，Mapped/mapped_column/relationship 来自 sqlalchemy.orm，列类型、约束和索引来自 SQLAlchemy，DatabaseModel 来自 oldman.db.models，`_` 是 gettext_lazy。其后还有 ExampleProject 等映射类，不能只复制 Team 而漏掉关系另一端：

```python
class ExampleTeam(DatabaseModel):
    """Team used to group projects in table and form examples."""

    __tablename__ = "example_team"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override
    __table_args__ = (
        UniqueConstraint("slug", name="uq_example_team_slug"),
        Index("ix_example_team_region", "region"),
        Index("ix_example_team_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    projects: Mapped[list[ExampleProject]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
    )

    class Meta:
        """Provide labels for automatic Admin presentation."""

        verbose_name = _("Example Team")
        verbose_name_plural = _("Example Teams")
```

`oldman.db` 公开 `Base`、`DatabaseModel`、`ModelMetadata`、`DatabaseManager`、`DatabaseNotConfiguredError` 和进程级 `db_manager`。DatabaseModel 是共享 Base 的抽象子类，没有自动 id；业务自己声明主键。没有显式表名时 Base 使用类名的小写形式，建议真实项目显式命名。

时间列存的是无时区 UTC。需要“现在”时用 `oldman.utils.date.naive_utcnow`（`default=naive_utcnow`、`onupdate=naive_utcnow`，代码里 `naive_utcnow()`），不要在每处写一遍 `datetime.now(UTC).replace(tzinfo=None)`，也不要让同一列出现带时区和不带时区两种值。

App Registry 根据已注册包的 models 模块加载模型，记录所属 App、Table、展示名和 managed 状态。不扫描所有安装包，也不应在 App 元数据模块中提前导入模型。一个 Table 只能归属一个 App；独立的关联 Table 也必须在该 App 的模型模块树中声明。模型模块拆成包时，由其 models/__init__.py 显式导入各子模块。

Demo 服务 YAML 的 apps 包含 `apps.examples`，该包的 [apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) 声明 label 为 `examples`。因此包路径、App label、Python 类名 ExampleTeam、数据库表名 example_team 是不同标识，不能混用。已有迁移随 [migrations](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/apps/examples/migrations) 保存；查看示例不需要每次重新生成它们。

Meta 支持 `verbose_name`、`verbose_name_plural` 和 `managed`。展示名可用 `gettext_lazy`，在具体请求时翻译；默认单数由类名生成，复数在单数后加 s，不规则名称应显式指定。`managed=False` 只表示不由迁移管理表结构，**不是禁止 ORM 写数据的权限开关**。外部表规则见迁移参考。

普通 ForeignKey、relationship、索引与约束使用 SQLAlchemy。不要把一套独立 DeclarativeBase 的模型混入框架 Registry，或在视图函数内临时声明映射类。

## 配置和延迟连接

Demo [data/web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) 的数据库节点：

```yaml
database:
  url: sqlite+aiosqlite:///data/epg_dashboard.db
  echo: false
  enable_sql_logging: false
```

常用驱动是 SQLite/aiosqlite、MySQL/aiomysql、PostgreSQL/asyncpg。服务需要安装所选异步驱动；没有 URL 时允许配置加载，但实际请求会话会抛 DatabaseNotConfiguredError。URL 中的密码不要提交。

db_manager 是进程级惰性实例，第一次进入会话时初始化 engine，打开连接仍由实际数据库操作触发。`engine` 属性不会替你执行异步初始化，提前读取会报错；需要直接操作 engine 时先 `await db_manager.initialize()`。

每个服务进程有自己的连接池，不是所有 Sanic worker 共用一个池。非 SQLite 的默认 pool_size=100、max_overflow=10、pool_timeout=30 秒、pool_recycle=1800 秒；部署时需要按进程数评估数据库连接上限。这些构造参数可覆盖，不是当前 YAML 的全部可配置字段。SQLite 不套用服务端连接池默认值，并为每个连接启用外键约束。

DatabaseManager 接受 DatabaseConfig 或返回它的同步函数，及可选 debug、pool_size、pool_class、max_overflow、pool_timeout、pool_recycle、enable_sql_logging。DatabaseConfig 来自 `oldman.conf.schemas`。这些是构造接口说明；Demo 使用框架的 db_manager，没有在业务里另建一个 manager。确需显式创建时，由调用方管理 close；创建 manager 不创建表，也不自动注册模型。

## 一个业务操作，一个写事务

Demo 的 [apps/examples/services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py) 以如下完整函数给静态项目表格提供数据。select/selectinload 来自 SQLAlchemy，db_manager 来自 oldman.db，ExampleProject 来自同 App 的 models：

```python
async def list_projects(limit: int = 12) -> list[ExampleProject]:
    """Return deterministic database rows for the static Table examples."""
    async with db_manager.get_read_session() as session:
        result = await session.execute(
            select(ExampleProject)
            .options(selectinload(ExampleProject.team))
            .order_by(ExampleProject.id.asc())
            .limit(limit)
        )
        return list(result.scalars())
```

返回的是已经读取字段和 team 关系的模型列表，不是仍待执行的查询。视图用于 `/examples/tables/static` 和 `/examples/tables/responsive`；关系预加载不能省掉后再让异步模板隐式查数据库。

写事务可以由视图持有，并传给服务函数。下面是 [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py) 的完整发布入口，对应 `/examples/charts/realtime` 页面中的按钮：

```python
@app.post("/examples/charts/realtime/publish", name="example_realtime_chart_publish")
@csrf_protect()
@admin_required()
async def example_realtime_chart_publish(request: Request):
    """Commit one metric, then publish it through the configured SSE Redis channel."""
    server_id = _server_id(request)
    async with db_manager.get_session() as session:
        try:
            payload = await services.create_server_metric(session, server_id)
        except ValueError as exc:
            raise BadRequest("Unknown example server") from exc
    published = await SSEPublisher.from_settings().publish_stream(
        stream=services.realtime_chart_stream(server_id),
        event=CHART_EVENT,
        payload=payload,
    )
    if not published:
        return api_response(
            DefaultApiResponse(
                error_code=ApiErrorCode.INVALID_REQUEST,
                message=_("The metric was saved, but Redis delivery failed."),
            )
        )
    return api_response(
        DefaultApiResponse(
            message=_("A new database metric was published."),
            actions=[
                FeedbackAction(title=_("Realtime metric published."), icon="success")
            ],
        )
    )
```

app 是模块通过 oldman.web.routing.get_app() 取得的实例，Request、BadRequest、CSRF 和响应类型从框架导入，admin_required 来自 Demo；`_server_id()`、CHART_EVENT 在同文件，services 指向 apps.examples.services。SSE 使用配置里的 Redis，初始化与浏览器接线见[实时示例](../agents/realtime.md)。不要为了抄这个数据库例子而给不需要实时推送的业务强加 SSE。

`create_server_metric()` 在调用方 Session 中读取服务器和最近样本，构建 ExampleServerMetric，最后 `session.add(metric)`、`await session.flush()`，返回强类型 payload；它不自己 commit。值是用于展示的确定性下一条样本，不是实际服务器监控采集。只有显式点击发布才写一条记录。事务退出后才 publish，Redis 发布失败不撤销已经提交的样本，也不能据此自动重试数据库写入。

| 接口 | 实际行为 |
| --- | --- |
| `get_session(request_info="")` | 创建写 Session；正常离开提交，异常离开回滚；最后关闭并处理本次文件候选 |
| `get_read_session()` | 创建 autoflush=False 的读 Session；不自动提交，最后关闭；不是数据库层只读权限 |
| `transaction(nested=False)` | 创建一个新 Session 并管理其事务；不是复用已有请求的 Session |
| `initialize()` | 幂等初始化当前 manager 的 engine 和会话工厂 |
| `close()` | 释放 engine/连接池和跟踪器，后续使用可重新初始化 |

flush 发送 SQL、取得数据库分配的 id，但事务仍可能回滚。不要在进入 get_session 后又手动 commit，再指望该上下文继续替你维护同一事务。需要同一事务内的 savepoint，使用已有 `session.begin_nested()`；`db_manager.transaction(nested=True)` 会另建 Session，不会给调用者已有的 Session 增加 savepoint。

一个 AsyncSession 不能给多个并发任务共用。任务要独立事务就分别创建会话；需要原子操作则在同一协程、同一会话中依次完成。不要把 Session 保存到全局变量或跨进程传递。

关系数据在会话内通过显式查询或 selectinload/joinedload 等加载。异步 ORM 关闭会话后访问尚未加载的关系，不会自动得到一个可 await 的查询；最好在会话内构造响应数据。

业务异常应穿过写上下文触发回滚。若在上下文里面捕获异常并正常退出，未回滚的其他修改仍可能提交。需要向浏览器推送结果、发送外部请求时，把这些动作放在成功退出写上下文之后，不把数据库与 Redis/网络当作一个事务。

## DatabaseModel 便捷方法的边界

| 方法 | 返回与注意事项 |
| --- | --- |
| `get_by_id(session, pk)` | 对象或 None；只支持单列主键 |
| `get_by_fields(session, options=None, **kwargs)` | 单个匹配对象或 None；多行匹配仍是查询错误 |
| `get_many_by_ids(session, ids)` | 主键到对象的字典；空输入返回空字典，只支持单列主键 |
| `get_many(session, **kwargs)` | 所有匹配对象；不会替你限制数据量 |
| `execute_query(session, *conditions, page=None, page_size=None)` | 不分页返回列表；分页返回 PageResult |
| `execute_query_with_select(session, query, page=None, page_size=None)` | 同上，接收自定义 Select |
| `add_to_session(session)` | 只 add，返回实例，不提交 |
| `save(session)`、`update(session, **kwargs)`、`delete(session)` | **会自行提交**；不适合混进上面的组合事务。`update()` 遇到模型上不存在的字段名会抛 `AttributeError`,不会静默跳过 |

ModelForm.save 与 DatabaseModel.save 不是同一个接口。前者的 commit=True 仅 add/flush，后者会 commit。组合业务优先使用 session.add、session.delete 和 flush，避免方法名相似造成提前提交。

模型还提供 model_dump_dict、model_dump_json、model_validate_json，供明确的序列化场景使用；它们不是任意 HTTP 输入的字段白名单。不要直接反序列化客户端对象后保存权限字段。

可从 `oldman.db.models` 导入 NativeTimestampsMixin、UtcTimestampsMixin、UUIDMixin、SoftDeleteMixin，但它们不全是跨数据库无差别的默认模型：时间戳 mixin 的服务端表达式带数据库方言假设，UUIDMixin 使用 PostgreSQL UUID/default。选用前核对目标数据库；最小 SQLite 示例用普通 mapped_column 声明。SoftDeleteMixin 只提供字段，不自动改写 delete 或过滤所有查询。

## User 的真实外键

配置入口是 Auth App 的 `app.settings.user_model`，YAML 为 `app_settings.auth.user_model`。选中的类必须继承 `oldman.auth.AbstractUser`，实际表始终是 `oldman_user`，主键始终是自增 Integer 的 id。不能改表名、核心字段或主键类型。

业务直接声明 `ForeignKey("oldman_user.id")`，按数据语义选择 ondelete；真实外键不需要动态猜 User 类的表名。自定义 User 可以增加列、索引、关系和方法，其 App 必须在服务 apps 中注册。所有启用 Auth 的服务必须选择相同的 User 类，见[迁移与 Auth](migrations.md#user-扩展的迁移)。

Demo 配置实际选择 `apps.auth.models.OldmanUser`；[该类](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/models.py) 继承 AbstractUser，目前仅明确表名和展示 Meta，没有添加额外用户列。不要把它描述成已经展示了所有 User 扩展迁移场景。

## 关闭与失败

当前 Application 的默认收尾**没有自动关闭 db_manager**。EPG Demo [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) 在 WebService 类中采用下面的完整方法，WebApp 来自 oldman.web.routing，db_manager 来自 oldman.db：

```python
    async def before_server_stop(self, app: WebApp) -> None:
        """服务停止前关闭数据库连接池。"""
        await super().before_server_stop(app)
        await db_manager.close()
```

父类先停止 worker 后台任务，随后 Demo 关闭本进程的数据库连接池；不要在每个 HTTP 请求结束时 close，也不要另外复制一个 after_server_stop 再重复关闭。普通 SimpleApplication、自定义命令和独立脚本需在自己对应的收尾/finally 中关闭由自己使用的 manager；专用 Taskiq Worker 的共享数据库池由框架退出链路关闭，实际 Demo 和区别见[Taskiq 生命周期](distributed-tasks.md#app-与服务加载)。

显式创建的 DatabaseManager 同样由创建者负责关闭。`enable_sql_logging=True` 增加查询跟踪与汇总，request_info 可标记业务位置，生产环境不要无条件打开详细 SQL 输出。

`create_db_and_tables()` 只用于低层隔离测试建立当前受管 metadata，不升级已有表，不建立迁移历史。生产和教程部署统一使用 db migrate。文件替换、删除与回滚时的额外处理见[文件生命周期](storage.md#模型文件的替换与删除)。
