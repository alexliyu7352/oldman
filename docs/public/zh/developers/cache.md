# 缓存

`oldman.cache` 缓存可重新计算的数据。它不负责 Session、任务队列或浏览器消息；Redis 连接本身由 [provider](providers.md#redis-连接)管理。不要把缓存成功写入当作业务数据已经持久保存。

数据库模型的行与查询结果由 `oldman.db.sqlalchemy.cache` 缓存，写入提交后自动失效，见[模型缓存](#模型缓存)。

## 选择对象和配置

公开入口是 BaseCache、MemoryCache、RedisCache、TwoLevelCache、memory_cache、redis_cache、cache_async_response 和 cache_response。

| 对象 | 数据在哪里 | 适合什么 |
| --- | --- | --- |
| `memory_cache` / `MemoryCache()` | 当前 Python 进程的字典 | 小量、允许各 worker 短暂不同的临时结果 |
| `redis_cache` / `RedisCache(...)` | 配置的 Redis 数据库 | 多进程共享的可重算结果 |
| `TwoLevelCache(memory, redis)` | 本进程内存加 Redis | 明确接受本地副本陈旧的读多场景 |

EPG Demo 的公开 YAML 中显式配置 CACHE 连接（节选，不是完整配置）：

```yaml
redis:
  CACHE:
    redis_url: redis://localhost:6379/2
```

Demo 的统计缓存使用显式 RedisCache 对象，见下一节，不读取根 cache 的 namespace/serializer。框架另提供进程级 `redis_cache`：它在首次操作时读取根 cache 配置并绑定，单纯 import 不连接 Redis。根 cache 只有 client、serializer 两项，不包含 enabled 或默认 ttl；键前缀是服务命名空间下的 `<core.namespace>:cache`，不单独配置。

需要多个业务缓存空间时直接构造 RedisCache 并指定各自 namespace。可以传实现 async_get_bin_conn 的 provider 对象，不必注册另一套缓存工厂。RedisCache 要求非空 namespace，绑定后不可修改。

MemoryCache 默认没有容量上限、没有淘汰算法；默认 NullSerializer 保存原对象引用，不复制 dict/list。不要把它当成跨进程缓存，也不要缓存仍会被其他代码修改的共享对象而期待自动隔离。

## Demo 中的实际使用

实际实现位于 [apps/examples/cache_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_example.py)，由受保护的 [views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py) 调用。运行服务先完成 bootstrap；不在未初始化的 Python Shell 中直接执行其数据库函数。

下面是该模块的连续节选。省略的 import 仍可在原文件找到：`datetime as dt`、`Literal/TypedDict/cast`、SQLAlchemy 的 `func/select`、实际 `ExampleProject` 模型、`oldman.cache.RedisCache` 与 `oldman.db.db_manager`。这是带数据库和 provider 依赖的业务代码，不是一个无前置的独立程序。

```python
CACHE_TTL = 30
CACHE_KEY = "counts"
# This namespace owns only the Demo statistic, never Session or other cache keys.
project_cache = RedisCache(
    "CACHE",
    namespace="oldman_epg_dashboard:examples:project-statistics",
    serializer="json",
    timeout=5,
)


class ProjectStatistics(TypedDict):
    """JSON-compatible snapshot; its source is determined on each read."""

    counts: dict[str, int]
    total: int
    calculated_at: str


async def read_project_statistics(
    *, refresh: bool = False,
) -> tuple[ProjectStatistics, Literal["cache", "database"]]:
    """Use a cached snapshot unless missing or explicitly recalculating it."""
    if not refresh:
        cached = await project_cache.get(CACHE_KEY)
        if cached is not None:
            return cast(ProjectStatistics, cached), "cache"

    statistics = await calculate_project_statistics()
    await project_cache.set(CACHE_KEY, statistics, ttl=CACHE_TTL)
    return statistics, "database"


async def calculate_project_statistics() -> ProjectStatistics:
    """Read one fresh snapshot; cache and process examples share this same query."""
    # Concurrent misses may repeat this small read-only query; no lock is needed.
    async with db_manager.get_read_session() as session:
        rows = await session.execute(
            select(ExampleProject.status, func.count())
            .group_by(ExampleProject.status)
            .order_by(ExampleProject.status)
        )
        # The result has keys() — its column names — so dict() would read it as a mapping; take the rows.
        counts = dict(rows.all())
    return ProjectStatistics(
        counts=counts,
        total=sum(counts.values()),
        calculated_at=dt.datetime.now(dt.UTC).isoformat(),
    )


async def clear_project_statistics() -> int:
    """Delete just this shared Demo snapshot; do not clear the Redis database."""
    return await project_cache.delete(CACHE_KEY)
```

函数返回的 `source` 只描述本次读取，不存入 Redis。首次查询只有一次按状态分组的 SELECT；没有行时 counts={}、total=0，仍保存含时间的完整快照。命中不调用数据库，也不会 touch TTL；显式 refresh 绕过 get，计算后重新设置 30 秒。

POST 成功后，视图渲染 `_result.html` 并调用 `replace_html_response(html)`；普通 ExamplesPage 执行动作，目标来自按钮的 `data-om-target="#cache-result"`。GET 页面不查询统计。三个 POST 有登录与 CSRF 保护；所有登录用户共用同一 key，不是按当前用户隔离的私有缓存。

RedisCache 的 timeout=5 是缓存操作超时，与 TTL=30 无关。缓存/数据库异常向上传递，不变成 miss 或空统计，由既有 HTTP/Feedback 显示失败。清除只调用 delete；CRUD 不自动失效本例快照，手动刷新用于观察已有 Table/Modal 修改后的数据。详细操作步骤见[用户教程](../users/cache-and-http.md)。

不存在的 key 返回 default；缓存值为 None 时也按 miss 处理。0、False、空字符串和空列表则是有效命中。需要区分“值为 None”和“没有缓存”时，把结果放入例如 `{"value": None}` 的业务对象。

## BaseCache 操作合同

所有操作均为异步。key 接受 str 或 int；namespace 非空时实际 key 为 `namespace:key`。

| 接口 | 返回与注意事项 |
| --- | --- |
| `get(key, default=None, loads_fn=None)` | 解码后的值或 default |
| `set(key, value, ttl=..., dumps_fn=None)` | bool，覆盖已有值 |
| `add(key, value, ttl=..., dumps_fn=None)` | bool，仅 key 不存在时添加；已存在抛 ValueError |
| `multi_get(keys, loads_fn=None)` | 与输入顺序一致的列表，缺失位置为 None |
| `multi_set(pairs, ttl=..., dumps_fn=None)` | bool，pairs 是 `(key, value)` 序列 |
| `delete(key)` | 实际删除数量 |
| `delete_match(pattern)` | 删除当前空间中匹配项的数量；pattern 是 glob，不是正则 |
| `exists(key)` | bool |
| `expire(key, ttl)` | 后端是否完成过期设置；ttl=0 表示移除过期时间 |
| `ttl(key)` | 剩余秒数；-1 无过期，-2 不存在 |
| `clear()` | 清空该实例拥有的空间，不是通用清库命令 |
| `close()` | 释放该实例拥有的资源 |

构造时 timeout 默认 5 秒，ttl 默认 None。每次操作还可传关键字 timeout；timeout=None 或 0 关闭操作超时。TTL 是数据存活时间，不是请求超时：省略 set/add 的 ttl 使用构造默认值，显式 None 或 0 表示不设过期。使用正数 TTL；不要依赖不同后端对负值的行为。批量输入应非空，空集合由调用方直接跳过。

Redis clear/delete_match 通过 SCAN 分批删除当前 namespace，namespace 中的 glob 字符会按字面处理；不是 FLUSHDB，也不是与并发写入隔离的数据库快照。MemoryCache.clear 清理自己整个字典及计时器。

RedisCache.close 不关闭 provider 连接；共享 Redis 由 Application 收尾或独立脚本的 `await redis_client.close()` 关闭。MemoryCache.close 会丢弃本实例数据；两者都支持 async with。自己创建的 MemoryCache 应在拥有者结束时关闭；Application 默认关闭的是全局 memory_cache。

## 序列化与错误

RedisCache 默认使用 pickle；示例显式使用 json。可选名称为 pickle、json、msgpack、null（名称不区分大小写）；类从 `oldman.serializers.cache` 导入，也可传 BaseSerializer 子类实例。

- JSON/MessagePack 适合结构化值，不保证还原任意 Python 类。
- Pickle 可以保存 Python 对象，但只能读取可信存储中的数据；不允许不可信客户端写入这些 key。
- NullSerializer 不编码，适合内存或调用者已经准备好 Redis 可存的 bytes/标量；不能用它直接向 Redis 写任意 dict。
- dumps_fn/loads_fn 只覆盖这次操作，读写格式必须由调用者配对；切换 serializer 不会自动转换已有数据。

普通 Cache 操作的连接、编码、解码及超时异常会向上传递，不自动返回“缓存未命中”。业务若允许降级可在自己的缓存读写处捕获相应异常，但不要吞掉实际数据库或业务函数异常。

## 两级缓存没有全局失效通知

实际 Demo 为 [cache_levels.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_levels.py) 的 CacheLevels Command，运行 `./run.sh web cache-levels`。已导入 MemoryCache、RedisCache、TwoLevelCache；命令自己持有 MemoryCache，RedisCache 使用 CACHE 别名、JSON 和每次 UUID namespace。统计来自上面的 calculate_project_statistics，不写数据库。`levels = TwoLevelCache(memory, shared)` 组合这两个具体对象，没有新的全局代理。

先把真实快照保存到 MemoryCache，以 0.15 秒 TTL 观察命中和 0.2 秒后过期。随后 levels.set(..., ttl=30) 同时写两层，受控子进程运行同一模块的 `_peer`：先 bootstrap_service("web")，之后才导入模型查询函数；自己的 MemoryCache 为空，重新查询后更新同一 Redis key。父命令输出两个真实 PID、更新前后 calculated_at、local_stale=true：直接读 Redis 得到新快照，levels.get 仍返回旧的本地快照。数量相同是正常的，数据库未变，计算时间来自两次真实查询。

父命令删除自己的 memory key 后再次 levels.get，才得到更新值。接着把 Redis TTL 改短、清理本地并回填，等待两层到期；最后重新 set 后 delete，确认两层同时缺失。短 TTL 只是让有限 Demo 快速可观察，不是推荐的生产配置。所有断言均对实际 Cache 结果；异常向上抛出，命令非零退出。父命令 finally 只清空自己的 UUID namespace，关闭内存计时器及本进程 Redis/数据库；子进程同样关闭自己的连接。清理不会碰 Web 页面原有统计、Session 或其他命令的 namespace。

get 先读内存，再读 Redis；默认用 Redis 剩余 TTL 回填内存，无过期则本地也无过期。get 的显式 ttl 可以改变本次回填时间。set/delete/clear 先操作 Redis，再操作当前进程内存；set 省略 ttl 时两层都无过期，不继承各层构造默认 TTL。

**其他 worker 已有的内存副本不会随这次更新而失效。** 因此它不能用于要求立即一致的权限、登录失效或计费状态。需要共享读取结果立即可见就直接用 RedisCache；不要凭 TwoLevelCache 的名字假定存在广播订阅。

## 函数结果与 HTTP 响应缓存

实际函数示例是 [cache_functions.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_functions.py) 的 CachedStats Command，`./run.sh web cached-stats` 由服务命令完成 bootstrap 后调用。局部 statistics 异步函数只调用上面的 calculate_project_statistics，用 `@cache_async_response(timeout=1, prefix=prefix)` 装饰；prefix 含 UUID，因此不影响其他运行。连续两次计算时间相同，1.1 秒后改变，最后 delete_match 仅删除本次 prefix；finally 关闭命令拥有的数据库和 Redis。装饰器的 timeout 在这里是结果 TTL，不是函数执行超时。

`@cache_async_response(timeout=3600, prefix="cache_fun_response")` 缓存异步函数返回值。key 使用 prefix、函数名及参数字符串拼接；不是函数参数的无碰撞结构编码。为业务设置独立 prefix，避免带复杂对象或不稳定 repr 的参数。缓存读写失败记录 warning 并继续执行业务；函数自身异常继续抛出。它不合并并发 miss，同一昂贵计算可能同时执行多次。

`@cache_response(key_prefix="response", expiration=3600, invalidate_paths=(), vary_by=None, use_pickle=True)` 用于 Sanic 视图：

- GET/HEAD 共用按原始路径、规范化查询参数和 vary_by 结果生成的 key。查询参数名排序，重复参数值顺序保留。
- 只保存 handler 返回的状态 200、非流式、没有 Set-Cookie 的响应；只存正文、状态、content-type 和可保留的 headers，不存整个 Request。
- 写方法 POST/PUT/PATCH/DELETE 在 handler 正常返回后清除当前路径及 invalidate_paths 的全部 query/vary 版本。返回业务错误但没有抛异常也会失效。GET/HEAD 不能配置 invalidate_paths。
- invalidate_paths 中的占位符来自视图 kwargs；必须使用与读取端相同 key_prefix。
- 缓存故障记录 warning，继续原视图或返回已生成响应；这不是让业务写入与失效组成原子事务。

它不自动读取浏览器 Vary、语言、Cookie、权限或租户来隔离结果。只给明确可缓存的响应使用；带用户数据时必须设置完整 vary_by，而且认证/权限必须先于缓存命中执行。会在后续中间件添加 Cookie 或含 CSRF 的页面，不因 handler 此时没带 Set-Cookie 就适合缓存。

实际网页消费者仍在 [views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py)，不是另一份虚构视图：GET `/examples/cache/response` 的装饰顺序是 router.get → login_required → cache_response。RESPONSE_PREFIX 为本例独立常量，expiration=5、use_pickle=False，vary_by 返回 request.ctx.locale。未命中时查询 SQL、异步渲染 `_response_result.html`，再 replace_html_response；命中时复用整个 JSON action 响应。它只含所有登录用户共享的项目数量/时间，不含身份、令牌或 Set-Cookie；权限不会因为缓存命中而跳过。

POST 同一路径的顺序是 router.post → csrf_protect → login_required → cache_response，使用同一个 key_prefix/use_pickle。handler 返回“已失效”片段后，现有装饰器删除 GET 所有 query/locale 版本；无需重复手写删除规则。按钮目标为 #cache-response-result，不与原 #cache-result 混用；前端仍是 data-om-action 和既有替换生命周期。统计 HTML 正常转义，翻译发生在生成片段时，语言隔离保留到缓存 key。原30秒 RedisCache 页面与这份5秒 HTTP 缓存互不失效。

两个装饰器都使用根 redis_cache，连接由 settings.cache.client 决定，键在 `<core.namespace>:cache` 之下；公开 Demo YAML 未覆盖 cache，默认 client 为 CACHE。use_pickle=False 控制 HTTP 响应封装的编码，不是切换 provider。Web 请求不关闭共享池，Application 收尾；CLI 示例才在 finally 关闭自己的连接。实际命中/到期、POST 失效、相同 URL 的语言隔离、匿名401和坏CSRF403已在隔离 Demo 验证，操作步骤见[用户教程](../users/cache-and-http.md#观察函数结果和整份-http-响应缓存)。

`oldman.cache.utils` 还提供 set_cache/get_cache/get_cache_expiration/delete_cache/delete_cache_many 的下划线拼接 key 便捷函数。它们使用原生 redis_cache namespace，不是 Django key，也不提供分布式锁。

## Django 缓存互操作

这是 `oldman.compat.django.cache` 的专门用途，不是 Oldman 原生缓存的默认格式。双方必须使用相同 Redis 数据库，以及 Django 内置 Redis backend 的默认空 KEY_PREFIX、VERSION=1 和默认 codec；不适配自定义 KEY_FUNCTION、前缀、版本或第三方 backend codec。[Django 缓存配置](https://docs.djangoproject.com/en/5.2/topics/cache/#redis)

Oldman 一侧仍使用 settings.cache.client 对应的**二进制** provider，但忽略原生 namespace 和 serializer，读写 `:1:<key>`。普通整数保留整数编码，bool/None/其他值使用 Pickle；Redis 及写入者必须可信。

真实入口为 Demo [django_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/django_cache.py) 的 DjangoCacheDemo，运行/可选隔离安装见[用户教程](../users/cache-and-http.md#可选与-django-交换缓存)。Command 执行时才 importlib.import_module("django.core.cache.backends.redis")；缺 Django 的模块导入失败给出明确说明，不让整个 commands.py 因可选依赖缺失而无法加载。

它从 settings.redis[settings.cache.client] 读取 URL 和 protocol，构造真实 backend.RedisCache(..., {"OPTIONS": {"protocol": config.protocol}})。Django 的 aget/aset/adelete 使用其原有异步入口，本例不在事件循环直接调用同步网络方法。项目统计来自 calculate_project_statistics，incoming/outgoing 使用本次 UUID key，missing 是独立 object sentinel。真实循环中的节选：

```python
                await django.aset(incoming, value, timeout=30)
                received = await get_django_cache(incoming, missing)
                assert received == value and type(received) is type(value)
                await set_django_cache(outgoing, value, lock_timeout=30)
                received = await django.aget(outgoing, missing)
                assert received == value and type(received) is type(value)
```

value 依次为真实统计及边界值，不把自己实现的字节生成器当 Django。命令另外真实核对永久 None、缺 key、短 TTL 到期、0/-1 删除、version=2 的隔离和损坏 pickle 抛错。不会清整个库。finally 逐个删除自己 version=1/2 的已知 key；Django 5.2 Redis backend 的 close 没有实际释放池逻辑，这个可选示例显式断开其 `_cache._pools` 中的原生连接池，再关闭 Oldman provider/数据库。这里依赖的 Django 内部点只用于示例资源回收，不进入 Oldman 的生产适配层。

lock_timeout 在这里就是过期秒数，不是锁：None 永不过期，0 或负数删除已有 key。这与原生 Cache 的 ttl=0 **不同**。get_django_cache 可以通过显式 default 区分缺 key 和已存 None；损坏数据解码报错，不当作 miss。

set_api_cache/get_api_cache/delete_api_cache/delete_api_cache_many 在此模块使用下划线拼接及 Django key。相同模块的 cache_async_response 也写 Django key，但不吞 Redis 错误。随机 ID 映射工具不是安全令牌生成器，不能用于认证。

## 图片缓存

`oldman.cache.images.ImageCache(storage=None)` 使用现有 Storage 保存原图/WebP，用 settings.cache.client 的 Redis 有序集合保存过期元数据。构造前须已 bootstrap，使用默认 Storage 时还须完成 storages.init_app；可显式传 Storage。

`await cache_image(url, image_content)` 接收已经取得的 bytes，返回格式到逻辑文件名的字典；它不下载 URL。`await get_cached_image(url)` 返回仍有效的文件名或 None，命中会延长存活。默认 cache_timeout=30 秒、resize_percent=30；过期清理在写图片时触发，不是自动运行的后台服务。当前写入前确实执行数量清理：max_cache_size 默认 10000，按 Redis 集合中的**格式文件条目**计数，清理后又可能写入原图和 WebP 两项，因此不是严格图片数或总字节上限，也不承诺并发写入下的硬容量限制。

记录图片的 Redis 集合键是 `<core.namespace>:image_cache`，随服务命名空间隔离；Storage 里的文件名仍以 `image_cache/` 开头，多个应用共用一个 Storage 时要自己隔离存储位置。输出逻辑名还需由业务选择下载路由，不直接当作绝对 URL。

实际 [image_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/image_cache.py) 的 `ImageCacheDemo` 执行 `./run.sh web image-cache`：Pillow 生成自有 PNG bytes，TemporaryDirectory 提供 FileSystemStorage 的根，ImageCache(storage=storage) 显式选择它，不调用全局 storages.init_app。cache_prefix 是单级随机目录名，cache_set_key 也是本次随机 key；不会触及默认用户媒体目录或共享图片索引。

命令先 cache_image("demo:first", content)，用 `async with await storage.open(name)` 读取原图核对 bytes，再确认输出可被识别为 WebP。cache_timeout=1 秒只为快速演示，命中后实际核对 Redis score 增加。等过期后 get 返回 None，文件仍在；下一次 cache_image("demo:second", content) 才删除旧文件和集合条目。这个顺序不能写成“后台定时自动删文件”。最后故意传非图片 bytes，当前实现保存 original、日志记录 WebP 失败、返回只含 original 的结果；它不是上传合法性校验器，也不是失败就不保存任何内容。

ImageCache 没有自己拥有的连接池或 close 接口；命令 finally 删除自己的集合并关闭本进程 Redis provider，TemporaryDirectory 回收本次所有文件。正常命令输出 `Image Demo temporary files removed.`；复制到 Web 服务时不要关闭共享 provider，交给 Application。这里没有数据库查询/写入，没有增加新的 Storage facade 或图片下载器。

## 模型缓存

`oldman.db.sqlalchemy.cache` 把模型的行和查询结果缓存在 Redis：连接取 `settings.cache.client`，键在 `<core.namespace>:model_cache` 之下。与上面几种缓存不同，它不需要调用方删键——经 ORM 的写入提交后，受影响的条目自动失效。EPG Demo 的 `ExampleTask` 开启了它，页面 `/examples/cache/models` 逐项演示下文的失效规则，操作步骤见[用户教程](../users/cache-and-http.md#观察模型缓存)；本节的 `Channel` / `Programme` 是示意模型，不是 Demo 文件。

### 开启与调用

模型继承 `CacheableModel` 并加 `@cached_model(...)`。只有显式调用下面的缓存方法才读写缓存；`db_manager.get_session()`、`get_read_session()`、`WriteSession` 和其中的普通查询完全不经过缓存，也不因为缓存存在而多执行任何代码。

```python
from datetime import datetime

from sqlalchemy import ForeignKey, String, select
from sqlalchemy.orm import Mapped, mapped_column

from oldman.db import db_manager
from oldman.db.sqlalchemy.cache import CacheableModel, cached_model


@cached_model(partition_by=("channel_id",), invalidate_on=(Channel,))
class Programme(CacheableModel):
    __tablename__ = "programme"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channel.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime]


async def read_guide(day_start: datetime) -> None:
    async with db_manager.get_read_session() as session:
        rows = await Programme.cached_filter(session, Programme.channel_id == 5, Programme.starts_at >= day_start)
        one = await Programme.cached_get(session, id=10)
        many = await Programme.cached_get_many(session, [1, 2, 3])
        plain = (await session.execute(select(Programme))).scalars().all()  # 普通查询，不经过缓存
```

`Channel` 是同一 App 里的另一个模型，被 `ondelete="CASCADE"` 引用，所以必须写进 `invalidate_on`（见下文「写」）。

| `@cached_model` 参数 | 默认 | 含义 |
| --- | --- | --- |
| `instance_expire_seconds` | 3600 | 单行、字段查找条目的过期秒数 |
| `query_expire_seconds` | 300 | 查询结果条目的过期秒数；`cached_filter(expire_seconds=...)` 可按次覆盖 |
| `partition_by` | `()` | 分区列，见[分区](#分区) |
| `invalidate_on` | `()` | 这些模型经 ORM 更新或删除时，本模型的全部条目失效 |
| `db_manager` | 进程级 `db_manager` | 未命中时从它的缓存连接池查库；调用方 session 必须连同一个数据库 |

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `cached_get(session, *, use_cache=True, **fields)` | 一行或 None | 按字段查一行。条目记的是找到的那一行的主键，随这一行的写入失效。没找到不缓存；条件匹配多行时抛 `sqlalchemy.exc.MultipleResultsFound`（开不开缓存都一样），所以只对唯一字段使用 |
| `cached_get_many(session, ids, *, use_cache=True)` | 主键到行的 dict，键用调用方传入的写法（传 `"1"` 就是 `"1"`，命中与否都一样） | 每个主键一条条目，只随该行的写入失效；数据库里没有的主键不在结果里 |
| `cached_filter(session, *conditions, page=None, page_size=None, use_cache=True, expire_seconds=None)` | 列表；同时给 `page` 与 `page_size` 时为 PageResult | 生成的语句不带 ORDER BY |
| `Programme.get_cache_manager().execute_query(session, statement, page=None, page_size=None, *, use_cache=True, expire_seconds=None)` | 同上 | 需要排序、LIMIT 等 `cached_filter` 表达不了的语句时使用 |

开着缓存时，无论命中、未命中还是下文的绕过，返回的都是**游离的快照**：列属性齐全、有主键身份，但不在调用方 session 里；访问没加载的关联会抛 `DetachedInstanceError`，不会静默当成空。`use_cache=False` 就是普通查询，返回挂在调用方 session 上的对象。这个开关在四个方法里同名，而且只能按名字传：`cached_get(session, True)` 会报 `TypeError`，不会把 True 当成查询条件。

快照用于读。它来自已提交的数据，可能比调用方事务里看到的新，也可能落后一个失效窗口。先读后改的逻辑用普通 session 读（需要时加 `with_for_update()`）再改。对快照调用 `save(session)` 能写回并照常触发失效；`update(session, ...)` 不会写入，而是抛 `InvalidRequestError`，因为快照不在这个 session 里。

### 读

| 情况 | 行为 |
| --- | --- |
| 命中 | 一次 Redis 往返，不占数据库连接 |
| 未命中 | 从缓存连接池借一个连接，在一个新的短事务里查库（分页时计数与本页在同一事务），写入 Redis |
| 调用方 session 里有这个模型未提交的改动（新增、修改、删除，或调用过 `invalidate_cache_on_commit`） | 用调用方 session 查库，看得到自己的改动；不读也不写缓存 |
| 本进程刚提交过这个模型、失效还没写到 Redis | 用调用方 session 查库；不读也不写缓存 |
| Redis 出错 | 用调用方 session 查库，记 WARNING |
| 缓存连接池 1 秒内没有空闲连接 | 用调用方 session 查库，不写缓存，记 WARNING |

写进 Redis 的数据只来自缓存连接池里的新事务，从不来自调用方 session：调用方的事务可能早已开始（读到的是开始时的快照），也可能带着自己未提交的写入，存进去会让别的请求读到旧数据或从未提交的行。

### 写

增删改的写法不变，失效在提交后自动发生；只有绕过 ORM 工作单元的写入要自己声明。

| 写法 | 失效 |
| --- | --- |
| `session.add(obj)`、改属性、`session.delete(obj)`、`merge`，以及 `save()` / `update()` / `delete()`，提交后 | 自动：这一行、它写入前后所在的分区、所有不按分区的查询 |
| `session.execute(insert(M)...)`、`update(M)...`、`delete(M)...`、原生 SQL | 这些语句不触发 mapper 事件，缓存看不到。在同一事务里调用 `M.invalidate_cache_on_commit(session)`：提交后该模型全部失效，回滚则什么也不做 |
| 数据库级联：外键带 `ondelete="CASCADE"` / `"SET NULL"` / `"SET DEFAULT"` 或 `onupdate="CASCADE"` | 把外键目标模型写进 `invalidate_on`，目标经 ORM 更新、删除时本模型全部失效。目标表自己也有这类外键时，要沿链一直写到头：删一个团队，数据库删掉它的项目，也就删掉了项目的任务，所以任务要写 `invalidate_on=(ExampleProject, ExampleTeam)`。少写一级时 `@cached_model` 在声明阶段抛 `TypeError`，链上的表在声明时还没定义也抛（先导入它的模型）。级联指回本表（树形表的 `parent_id`）不用写，也写不了：这时本模型每次更新、删除都让本模型全部失效，树形表的命中率因此低于别的表，这是正确性要求的。目标用批量语句删改时，同样要调用本模型的 `invalidate_cache_on_commit` |
| 其他程序、手工改库、数据库触发器 | `await M.invalidate_cache()`，立即让该模型全部条目失效 |

提交不等待 Redis：最外层事务提交后，由一个任务用一次 pipeline 完成失效，最多等 5 秒。保存点（`begin_nested()`）释放时不失效，要等最外层提交——否则别的请求会在提交前把旧数据重新存进缓存。事务没有提交就结束（回滚，或不提交就关闭 session）时不失效。只回滚保存点、或保存点里 flush 失败时记录不丢弃，外层提交后连同保存点里被撤销的写入一起失效——多失效一次，不会漏。写入时取不到分区列的旧值（属性已过期又直接赋值），该模型全部失效。

### 分区

没有 `partition_by` 时，模型的任何写入都让它所有缓存的查询失效；单行和字段查找只随自己那一行失效。读写都多的模型可以声明分区列，通常是外键：

- 查询 WHERE 的顶层 AND 里，每个分区列都以 `列 == 值` 或 `列 IS NULL` 出现（布尔列也认 `flag == True`、`flag.is_(False)`、单写 `flag` 和 `~flag`），这条查询就只随该分区失效：只有写入前或写入后落在这个分区的行才会影响它。其余条件照常可加，结果一定在分区内。
- 不满足的查询（缺分区列、用 `IN` / `OR` / 范围比较、WHERE 里有子查询）随整个模型失效。
- 分区列只能是整数、布尔、UUID、枚举列，声明时检查。字符串、日期时间、小数、浮点不行：数据库按排序规则和精度比较（大小写不敏感、尾部空格、截断），与 Python 的 `==` 不同，会漏掉失效。

### 边界

| 何时报错 | 内容 |
| --- | --- |
| `@cached_model` 声明时，`TypeError` | 不是 `CacheableModel` 子类；不是单列主键；使用映射继承；有不支持的列类型（项目自定义的 `TypeDecorator`、`ARRAY` 等）；有延迟加载的列（`deferred=True`，它不随行加载，缓存存不了完整的行）；分区列不存在或类型不对；数据库级联外键链上的某张表不在 `invalidate_on`，或在声明时还没定义 |
| 调用缓存方法时，`ValueError` | 语句读了别的表（JOIN、子查询）、只选部分列、`with_for_update()`、带加载选项（`selectinload`、`load_only` 等）；带由函数算值的绑定参数（`bindparam(..., callable_=...)`，SQLAlchemy 的语句缓存键里没有它算出的值，两个结果会共用一条缓存）；调用方 session 连的数据库与 `db_manager` 不同；数据库是内存 SQLite（缓存连接池是另一个连接，看到的是另一个空库） |

支持的列类型：整数、字符串、布尔、浮点、`Numeric`、日期、时间、日期时间、`Interval`、`Uuid`、枚举、`LargeBinary`、JSON（含 `JSONText`）。读回的值与类型和直接查库一致，日期仍是 `datetime`，小数仍是 `Decimal`（`Float(asdecimal=True)` 也是），浮点的 NaN 与正负无穷照原样读回。枚举列在同一事务里被赋成成员名字符串时，快照读回的是枚举成员。模型增删列、改列名或改变列的类型表示后，缓存键随之改变，新部署不会读到旧代码存下的行。改 `partition_by` 或 `invalidate_on` 时键不变：滚动部署期间新旧进程按各自的规则失效，旧进程的写入可能让新进程的缓存留着过期的行，最长到过期时间。旧代码不知道新规则，这一点消除不了；部署全部完成后执行一次 `await M.invalidate_cache()`。

下面几条不会报错，由使用者注意：

- 缓存键由语句结构和参数值组成。`Programme.starts_at >= func.now()` 这类随时间变化的条件每次生成同一个键，会一直返回填充那一刻的结果；应把时间作为参数传入，并取整到可以接受的粒度（例如分钟），否则每次都是新键、从不命中。
- 所有列以 JSON 明文存进 Redis。含密码哈希、令牌、密钥的模型不要开缓存。
- 写入缓存模型的提交要发生在事件循环所在的线程里。在没有运行中事件循环的线程（同步脚本、`asyncio.to_thread` 里的代码）提交时，失效无法启动，只记 ERROR。

### 时间窗口

- 另一个进程在写入提交后、失效写到 Redis 之前（约一次 Redis 往返加上后台任务调度）可能读到旧值。本进程没有这个窗口：失效完成前，本进程对该模型的缓存读取直接查库。
- 失效失败（Redis 出错、超过 5 秒）不影响已经提交的写入，记 ERROR；受影响的条目最多错到过期，查询默认 300 秒，单行默认 3600 秒。
- 进程退出时，还没做完的失效会随事件循环结束被取消。框架的 CLI 命令、Web 与常驻服务、Taskiq Worker 在关 Redis 之前都会等本进程的失效做完（每个最多 5 秒）；等待被取消（例如按 Ctrl+C）时照常关闭资源。自己用 `asyncio.run` 或 `bootstrap_service()` 写的脚本，退出前要调用 `await wait_for_invalidations()`（从 `oldman.db.sqlalchemy.cache` 导入），否则最后几次提交的失效可能丢失。
- Redis 淘汰或过期掉失效用的计数键后，重建的计数是新的随机值，旧条目只会不命中，不会复活。

### 缓存连接池

未命中时的查库走 `DatabaseManager` 内部单独的连接池：第一次未命中时才建立，同一个数据库、同样的 engine 选项，`database.cache_pool_size` 个连接（默认 5，不溢出），等连接最多 `database.cache_pool_timeout` 秒（默认 1.0），`close()` 时一并释放。请求本身已占着主连接池的一个连接，若再从主池借第二个，高并发时请求之间会互相等待；单独的池让两者不会互相卡住，等不到连接时这次读取改用调用方 session。

```yaml
database:
  cache_pool_size: 5
  cache_pool_timeout: 1.0
```

两项都必须大于 0，在第一次建立缓存连接池时读取，改了要重启服务才生效。自建 `DatabaseManager` 时也可以用同名构造参数覆盖配置，同样必须大于 0，否则构造时抛 `ValueError`。每个服务进程最多多占 `cache_pool_size` 个数据库连接，评估数据库连接上限时要算进去。

### 值不值得开

本机实测：Redis 走 unix socket，SQLite 文件库，按频道查 50 行，两轮结果。

| 操作 | 耗时 |
| --- | --- |
| `cached_filter` 命中 | 578–607 µs |
| 同一查询直接在 session 上执行 | 554–581 µs |
| `cached_filter` 未命中（查库并写入缓存） | 1.5–1.7 ms |
| 一次提交的失效（后台，一次 pipeline） | 约 225 µs |

命中和本机 SQLite 上的简单查询差不多快，时间花在 Redis 往返、生成缓存键和把 50 行还原成对象上。命中的收益是不占数据库连接、不消耗数据库的算力：查询本身慢（大表、复杂条件）、数据库在网络另一端或连接池吃紧时才划算。写多读少的模型不要开，一次未命中大约是直接查库的三倍。

实际的命中率用 `Programme.get_cache_manager().stats` 看。它返回本进程启动以来的计数快照 `CacheStats`，每读一个条目计一次（`cached_get_many` 按主键计），`use_cache=False` 不计：

| 字段 | 含义 |
| --- | --- |
| `hits` | 从 Redis 返回 |
| `misses` | 经缓存连接池查库并写入缓存（没查到的不写） |
| `bypassed` | 调用方有该模型未提交的改动，或本进程的失效还没完成，改用调用方 session 查库 |
| `fallbacks` | Redis 出错或缓存连接池等不到连接，改用调用方 session 查库 |

计数只增不减，比较两次快照得到这段时间的情况；每个进程各算各的。计数本身的开销约 0.1 µs 一次，实测对命中耗时没有可见影响。
