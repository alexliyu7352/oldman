# 缓存示例与外部 HTTP

缓存减少重复计算；后端 HTTP Client 访问上游系统；Redis/NATS provider 提供具体基础设施。它们不替代必须长期保存的数据库记录。

## Demo 当前实际使用了什么

EPG Demo 的配置、服务和 Apps 已接入 Redis Session、SSE 与用户通知。实时图表的发布入口见 [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py)，它通过 SSEPublisher 发布，不由业务自己操作 Pub/Sub。

通用缓存的实际页面是 `/examples/cache/redis`，由真实项目表生成统计，再用 Redis 保存短期快照。下面可以直接在 Demo 操作；它不是 Session 或 SSE 的缓存。

后端 HTTP 的实际页面是 `/examples/http/client`：Python 请求配置的上游，浏览器显示诊断结果；不能将浏览器 HTTP Client 当成后端 MultiHttpClient。后台 NATS 事件/RPC 有独立的[通信教程](service-communication.md)，不属于本页的 HTTP 协议。

## 运行项目统计缓存示例

先按[运行教程](getting-started.md)初始化 Demo、迁移、导入 `demo` fixture 并创建工作人员账户。公开 [web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) 包含：

```yaml
redis:
  CACHE:
    redis_url: redis://localhost:6379/2
```

这是现有 YAML 中的节选，不要用它覆盖整个配置。Session、SSE 等别名仍保留。已有本地 `web_settings.yaml` 应核对 `redis.CACHE` 的实际地址；Demo 不替你启动 Redis，也不修改正在使用的配置。启动 `./run.sh web start` 后，登录并从侧栏“缓存 → Redis 缓存”进入，默认地址是 `http://127.0.0.1:17998/examples/cache/redis`。

按以下顺序操作：

1. 页面刚打开只有按钮和说明，不查询统计，也不会提前填充缓存。
2. 点击“读取统计”。没有快照时，后端按 `ExampleProject.status` 分组计数，显示“从数据库计算”、项目总数和 UTC 计算时间，并写入 30 秒 JSON 缓存。
3. 在 30 秒内再次读取。应显示“命中 Redis 缓存”，数量和计算时间不变；这次不查询项目表，也不延长过期时间。等 30 秒过期后再读，应重新计算。
4. 打开 `/examples/tables/html` 或 `/examples/tables/json`，在现有编辑 Modal 中修改一个项目的状态并保存。回到缓存页点击“从数据库重新计算”，应看到对应两组数量变化及新的计算时间；本例不自动监听 CRUD，未过期的普通读取允许显示旧快照。
5. 点击“清除本例缓存”，只删除这个统计 key。再次清除显示“没有需要清除的缓存快照”；下次读取重新查数据库。不要用清空 Redis 数据库来代替这个操作。

空项目表会显示并缓存零结果，不回填固定演示数字。所有 staff 用户共享这份统计，清除也影响其他用户的下一次读取；它不适合直接照搬为个人私有数据、权限或计费缓存。页面本身不写项目表，只有第 4 步的 CRUD 操作修改数据。

## 从实际代码看调用关系

| 文件 | 负责什么 |
| --- | --- |
| [cache_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_example.py) | 持有 RedisCache；读快照、数据库分组查询、写入 TTL、删除单 key |
| [views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py) | GET 页面；三个统计 POST；独立的响应缓存 GET/失效 POST；staff 权限与写操作 CSRF |
| [cache 模板目录](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/cache) | 两个缓存分区的按钮、说明、独立结果区域及片段 |
| [views/__init__.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/__init__.py) | 页面清单与具体路由模块导入；沿用现有 Examples App 注册 |

业务函数 `read_project_statistics(refresh=False)` 返回快照与本次来源；不是把“已命中”写进快照。`clear_project_statistics()` 调用同一实例的 `delete(CACHE_KEY)`。完整函数及类型说明见[Cache 参考](../developers/cache.md#demo-中的实际使用)。

前端没有缓存专用 TS。按钮的 `data-om-action="post"`、`data-om-url`、`data-om-target="#cache-result"` 交给当前 Page；视图调用 `replace_html_response(html)`，让普通响应执行器替换结果区域。复用时同时保留页面加载、CSRF 和权限接线，不能只复制一个 `fetch()` 或公开一个任意 Redis key 接口。

RedisCache 构造不连接 Redis，第一次操作才通过 provider 取连接。缓存操作超时为 5 秒，TTL 的 30 秒是数据有效期，二者不是一回事。连接、超时、序列化和数据库错误都向上传递，由已有 HTTP/Feedback 链路显示失败并结束 loading，不回退为假命中或零项目。复现故障应使用独立测试配置和 Redis，不停止正在供 Session/其他业务使用的服务。

缓存对象不拥有 Redis 共享池；不在每个请求结束时关闭它。现有 WebApplication 收尾关闭 Redis，Demo WebService 收尾关闭数据库。并发未命中可能重复执行这条小型只读查询；没有额外分布式锁、后台刷新或两级缓存。

## 观察内存缓存与两级缓存

数据库配置与前面的 Redis 统计页相同，但不需要登录、构建前端或启动 Web。已配置 CACHE Redis 并完成迁移后，在 Demo 根目录运行：

```bash
./run.sh web cache-levels
```

App 命令会加载 web 的配置；若启用 NATS/Taskiq，仍须准备相应设施，或在自己的测试 YAML 关闭它们。这个示例本身只需数据库和 Redis，不启动 Worker/Scheduler。

命令自动完成一次有限演示：

1. 从真实项目表计算统计，存入本进程 MemoryCache；立即读取命中，等待短 TTL 后消失。
2. 建立 TwoLevelCache，同时保存内存和 Redis 快照。
3. 一个真实子进程重新计算并更新 Redis。其新 MemoryCache 为空，父进程的旧内存不会跟着更新。输出 `before/shared_updated` 的真实计算时间以及 `local_stale=true`，不是伪造项目数量变化。
4. 删除父进程的本地副本，再读取便会从 Redis 回填新值；之后实际观察两层到期和显式删除。
5. 清理本次随机 namespace、内存计时器和两个进程的连接，不改变业务数据。Redis 离线时命令报错退出，不输出假命中。

源码 [cache_levels.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_levels.py) 的断言检查真实结果，正常输出中 memory_hit、memory_expired、backfilled、both_expired、both_deleted 都为 true。这个“其他进程更新、我仍读到旧值”的行为是两级缓存的已知边界，不是应添加广播来掩盖的示例错误；权限、登录状态等要求立即一致的数据不要照搬此模式。MemoryCache 默认没有容量限制，存入 dict/list 不会复制对象。

## 可选：与 Django 交换缓存

EPG `django-cache` 使用 Django 自带的 RedisCache，不模仿其格式，也不启动 Django 网站。框架和普通 Demo 不依赖 Django；只试本项时，在 Demo 根目录给本次命令提供隔离依赖：

```bash
demo_django_dir=$(mktemp -d /tmp/oldman-django-demo-XXXXXX)
uv pip install --python .venv/bin/python --target "$demo_django_dir" 'Django>=5.2,<5.3'
PYTHONPATH="$demo_django_dir" ./run.sh web django-cache
# 命令已结束后，确认这是上面创建的目录，再清理它。
rm -r -- "$demo_django_dir"
```

这里 PYTHONPATH 仅让本次 Python 命令找到可选库，不是通过环境变量配置业务 Settings。数据库/Redis 前置与 cache-levels 相同；Redis 地址从当前 `settings.cache.client` 指向的 alias 读取，不把凭据打印出来。没有可选依赖时，命令明确报错，其他命令和网页照常使用。

运行会真实检查 Django 写、Oldman 读以及反方向：项目统计、0、负整数、bool、None、中文和 bytes。输出中 bidirectional_values=8、types_preserved=true；随后验证 TTL、None 与缺 key、实际 1 秒过期、非正 timeout 删除。使用 version=2 写入的 Django 值不能被 Oldman 固定 version=1 的接口读到，输出 version_2_is_separate=true。最后故意给**本次 key**写入损坏数据，双方都必须报解码异常，不能把损坏值伪装成未命中。

源码是 [django_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/django_cache.py)。命令只读业务数据库、只写随机 key 并在 finally 删除，绝不调用 Django.clear（会清 Redis DB）。双方关闭自己的连接；不更换框架默认缓存编码。

互操作范围是同一 Redis DB、Django 默认空 KEY_PREFIX、VERSION=1 和默认 codec。自定义前缀、版本、KEY_FUNCTION 或其他 Redis backend 不会自动适配。Pickle 只能读取可信服务写入的数据；本命令不是证明任意外部 Redis 都安全。[Django Redis 配置](https://docs.djangoproject.com/en/5.2/topics/cache/#redis)及[框架精确合同](../developers/cache.md#django-缓存互操作)说明边界。

## 观察图片缓存的真实文件

运行 `./run.sh web image-cache`，只需当前 CACHE Redis；不查询业务表、不需要导入图片，也不启动网站。App 命令本身仍加载所选服务配置及启用的设施。

源码 [image_cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/image_cache.py) 在内存生成一张自有 64×64 PNG，把 bytes 交给 ImageCache。结果显示 Storage 逻辑名及实际 WebP 尺寸（默认 30% 缩放，本图为 19×19）。它不是让框架从 URL 下载图片；`demo:first` 只是缓存标识。

命令实际核对原图字节、WebP 可读取、命中延长有效期。等待 1 秒过期后，读取返回未命中，旧文件暂时仍在；下一次写入才执行过期文件清理。最后故意给一份损坏图片，日志会出现 WebP conversion failed，但当前 API 保留原始 bytes 并只返回 original。这是演示其真实部分失败行为，不是整个命令失败，也不能把缓存当上传图片校验器。

输出的五项检查都为 true 后，命令删除自己的随机 Redis 集合和 `/tmp` 图片目录，打印清理完成。文件只用于本次观察，结束后不会留在用户媒体库。图片缓存的容量按格式条目在写入前清理，不是严格总图片数或字节上限；详细默认值与资源归属见[参考](../developers/cache.md#图片缓存)。

## 观察函数结果和整份 HTTP 响应缓存

已有数据库和 CACHE Redis 后，运行 `./run.sh web cached-stats`。真实源码 [cache_functions.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_functions.py) 在命令内用 `cache_async_response(timeout=1, prefix=本次随机值)` 装饰同一统计查询。输出 first、cache_hit、after_expiry：前两个计算时间完全相同，等待 1.1 秒后的第三个时间改变。命令只读数据库，finally 删除自己 prefix 的 key、关闭数据库和 Redis；不用先启动网站。

网页上的另一个例子位于 `/examples/cache/redis` 下方“HTTP 响应缓存”分区。它缓存的是整份响应，不是上方的 30 秒统计值：

1. 点击“读取缓存响应”，后端查询真实项目数，返回含统计 HTML 的标准 JSON replace_html action。
2. 5 秒内再点，项目数量和计算时间不变。这里没有“刚刚查库”的徽标，因为整个响应都被复用，不能把第一次的来源标签当本次来源。
3. 等 5 秒后再读，计算时间应更新；数据库不变时数量当然可以相同。
4. 点击“失效响应缓存”，POST 同一路径，结果显示失效完成。它删除本例所有查询参数和语言版本，下次读取重新计算；不修改项目表，也不清上方的统计值 key。
5. 切换语言后读取，结果使用当前语言；从其他示例通过侧栏回来，按钮仍可用。未登录仍返回认证错误，POST 没有有效 CSRF 则拒绝；关闭公共错误提示后可再次操作。

实现是 views/cache.py 的 example_cached_response/example_invalidate_response，两个按钮共用普通 ExamplesPage，目标为 `#cache-response-result`，没有新增 TS 或组件。GET 的 staff 校验在缓存装饰器之前，按 request.ctx.locale 隔离；响应不含用户私有数据、CSRF 或 Cookie，不能直接复制成缓存个人账户页面。

这两个装饰器读取根 cache.client/namespace；公开 YAML 没有覆盖 cache，使用默认 client=CACHE。它们缓存故障时记录 warning 并继续查询/返回业务结果，数据库异常仍抛出。这与前面直接 RedisCache 操作不自动降级不同。缓存命中须看真实计算时间，不能把 Redis 离线后的成功查询说成命中。命令的检查要求 Redis 可用，否则会报错。完整签名、key 规则和不能缓存的内容见[开发者参考](../developers/cache.md#函数结果与-http-响应缓存)。

## 需要缓存时

- 多 worker 共享可重新计算的结果，使用 [RedisCache/redis_cache](../developers/cache.md)。
- 只需本进程临时结果，可用 MemoryCache；它不提供跨进程 Session 或权限失效。
- 用独立 namespace 和有限 TTL 表达数据归属、陈旧时间；不能清空共享 Redis 来重置一个示例。
- 数据库修改成功后再更新或失效缓存，不声称两个系统能够原子提交。
- 缓存故障是否降级由业务决定；不能吞掉真正的数据库或计算错误。
- Django 缓存互操作见 [Cache 参考](../developers/cache.md)，不能把它的 key/codec/TTL 规则混同于原生 Oldman Cache。

配置操作与命中、过期、None/False/0、多进程和资源关闭的具体合同都在参考页中。CACHE 连接用于缓存示例，不改变 Table 原有的数据库查询流程；TwoLevelCache 是独立 CLI 示例，不能把它当成已接入所有页面。

## 运行后端 HTTP 示例

使用同一个已经初始化、可以登录的 Demo，从侧栏“HTTP → 后端 HTTP 客户端”进入，默认地址为 `http://127.0.0.1:17998/examples/http/client`。本例不要求新增数据库表、导入额外数据或启动另一个 Oldman 服务。

公开配置中的上游地址是：

```yaml
app_settings:
  examples:
    http_base_url: https://httpbin.org
```

这是已有 YAML 的节选，不能覆盖整个 app_settings。旧配置没有这一项时使用 ExamplesSettings 的默认值，可通过 `./run.sh web settings sync` 补齐。需要自建环境时，将它改为自己部署的 httpbin 兼容实例，然后重新启动服务；基地址可以带路径前缀，不能带账号、密码、查询参数或 fragment。

只有点击按钮才访问上游；页面载入、服务启动、侧栏切换不会自动请求外网。公共上游会看到服务器出口地址、Demo User-Agent 和固定参数，不会收到浏览器登录 Cookie、用户输入或项目数据库记录。公共服务可能不可用、限流或提前返回延迟请求，不能据此关闭 TLS 验证。

按以下顺序操作：

1. 点击“读取 JSON”。Python 请求 `/get` 并携带固定 `example=oldman-epg-dashboard` 参数。结果区域显示实际 HTTP 状态、Content-Type、耗时和上游 JSON；不是页面预填的一组演示数字。
2. 点击“观察上游 404”。结果应明确显示上游 404 和失败状态。Demo 页面仍保留，不跳转到 Demo 的 404 页面。
3. 点击“观察超时”。上游接口请求延迟 10 秒，本例整个操作最多等待约 5 秒，不重试。上游如果提前返回，应显示它实际返回的结果；如果确实延迟，则显示超时，结束 loading 后仍可操作。
4. 点击“读取字节流”。请求 65536 字节；Python 逐块计数和计算 SHA-256，结束后显示实际字节数和摘要。不保存文件，不通过 SSE 发送浏览器进度。超过本例 1 MiB 限制则关闭响应，不给出假完整摘要。
5. 再读一次 JSON，确认前一次错误没有使客户端不可用。可从缓存页或其他页面通过侧栏进入本页，检查相同按钮仍能使用。

这里有两层 HTTP，不能混为一谈：浏览器请求 Demo，Demo 再请求上游。Demo 返回 HTTP 200 和 replace_html action，表示诊断结果成功送回；结果面板中的上游 404、超时、连接失败仍是失败，不因此变成成功。未登录、权限不足、CSRF 失败或 Demo 自身程序异常仍由既有认证/公共错误流程处理。

### 源码与资源归属

| 文件 | 负责什么 |
| --- | --- |
| [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py) | 持有客户端、四种请求、超时、诊断结果和流上下文 |
| [settings.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py)、[apps.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/apps.py) | Examples App 的强类型上游配置与注册 |
| [views/http.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/http.py) | staff/CSRF、操作白名单、页面与结果片段的渲染 |
| [HTTP 模板目录](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/http) | 四个按钮、目标区域、诊断文本；JSON 中的 HTML 不会被执行 |
| [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) | HTTP Client 的启动初始化与停止关闭，保留原框架收尾 |

本例没有专用 TS：按钮使用 `data-om-action="post"` 和 `data-om-target="#http-result"`，普通 ExamplesPage 执行视图返回的 replace_html。完整 Python 实现见[HTTP 参考](../developers/http-client.md#demo-中的实际使用)。

每个 worker 持有一个无用户凭据的 MultiHttpClient，选择 HTTPX、8 个连接、不重试、不跟随重定向、TLS 验证开启。服务启动调用 init_client，但直到第一次点击才建立真实网络连接；请求结束只关闭当前响应，服务停止才 close_client。不要把这个共享实例直接用于多个用户各自的上游登录 Cookie。

上游断开时，本页显示明确诊断；Session、Redis 缓存和其他页面不因此停用。故障验证应使用隔离配置和自有上游，不停止真实业务服务。当前示例不覆盖多 backend 对比、Cookie 登录、Storage 下载保存和断点续传，相关公开合同仍保留在参考页中。

## 在业务中调用外部 HTTP

使用 [MultiHttpClient](../developers/http-client.md)，不要在业务 App 再复制一套网络层。明确谁初始化、谁持有连接池、谁关闭：

- 一次性命令使用自己的调用生命周期，最终释放客户端。
- 长期服务复用连接池，不每个请求结束都关闭全局客户端。
- 按上游合同检查 HTTP 状态后解析正文，不能将异常转换为假成功或空对象。
- POST 等写入请求不因网络失败默认重试；可能已经被对方处理，需要业务明确幂等规则。
- URL、认证、代理和 TLS 来自可信配置，不把用户提交的任意 URL 当成安全上游。
- 大文件使用流式响应与现有 Storage，不先无界读入内存。

后端收到 JSON 中的业务错误码时，由后端业务解释，不交给浏览器 ResponseActionRunner。

## 其他连接

[Provider 参考](../developers/providers.md)解释命名 Redis 连接、Pub/Sub 和 NATS 的发布/RPC。Worker 控制消息、浏览器用户提示与外部基础设施是不同边界，不用一个含糊的 MessageBus 包起来。

补 Demo 时，应分别提供真实来源、可见结果、一条失败路径以及退出清理；不要用返回固定字典的“假上游”冒充完成网络接线。当前已有的可操作页面见[Demo 示例索引](demo-examples.md)。
