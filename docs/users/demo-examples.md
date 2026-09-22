# Demo 页面与源码对照

本页以 [EPG Dashboard Demo](https://github.com/alexliyu7352/oldman-epg-dashboard) 的实际页面为索引。先按[运行教程](getting-started.md)迁移、导入数据、创建账户、构建并启动；下列路径相对于 `http://127.0.0.1:17997`。端口改变时使用自己的地址。

下面的路径是阅读和操作入口，不是“所有场景已通过验收”的声明。页面有说明文字不等于已有功能：明确列为缺口的高级 Table 不作为可复制的完成示例。

## 如何对照

1. 浏览器打开对应页面，操作你要复用的那一项；先区分它是静态展示、只校验，还是写数据库。
2. 从对应视图找到实际 Form/Table/Service，再找到模板。不仅复制一个按钮。
3. 普通组件来自共享 Dashboard loaders。只有表格实时显示等私有行为才继续看 `frontend/src/components/examples/`。
4. 修改后在同一个 Demo 页面验证，也通过侧栏从其他页面进入一次，检查动态挂载是否正确。

示例统一入口与分类在 [views/__init__.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/__init__.py)。它会导入各具体视图模块；不要把所有 URL 都理解为一个只渲染空壳的通配路由。

## 自定义 App 命令

这项在终端操作，没有另建网页。先完成[入门教程](getting-started.md)的环境安装、配置、数据库迁移和 `./run.sh web loaddata demo`；不必构建前端、创建登录账号或启动 Web。已经准备过数据库就直接使用，不为统计重复导入数据。

在 Demo 根目录运行：

```sh
./run.sh web --help
./run.sh web project-stats --help
./run.sh web project-stats
./run.sh web project-stats --team-id 1
```

第一条在“Dashboard Examples”的本地化分组下列出 `project-stats`。统计命令输出项目总数和按状态分组的数量；`--team-id 1` 只看团队 1，替换成你要查询的真实 ID。总数取决于当前数据库，不写死 fixture 数量。可在[项目表格](tutorial-dashboard.md)新建或修改一条项目后再次运行，对照项目总数或状态数量变化；命令不会改项目、写缓存或投递任务。

Demo 默认启用了 `nats_bus` 和 `taskiq`，现有异步命令入口会先连接配置中的基础设施。按 Demo README 准备它们即可，不需要启动 NATS 接收服务、任务 Worker 或 Scheduler。若不试用通信和分布式任务，在本机服务 YAML 将 `nats_bus.enabled` 与 `taskiq.enabled` 都设为 false；统计自身只需要数据库，不会因 Web 配置启用了 Session/SSE 就连接这些 Redis 通道。

可安全验证参数失败：`./run.sh web project-stats --team-id 0`，应提示参数无效，退出码 2，而不是显示 0 个项目。不存在的团队会明确报错、退出 1；真实但没有项目的团队才显示 0 并正常结束。未迁移或数据库连接失败也报错退出，不偷偷建表。不要删除正在使用的数据库来试失败场景。

源码为 [commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/commands.py)，模型与网页共用 [ExampleProject/ExampleTeam](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py)。注册及完整代码说明见[CLI 参考](../developers/cli.md#自定义-app-命令)，专项检查在 [test_examples_commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/tests/test_examples_commands.py)，测试使用自己的临时数据库。

### 其他终端示例

这些命令也由Examples App提供，均在Demo根目录运行；`web`只选择当前配置，不启动HTTP服务。它们各自执行有限演示并退出，不要求另建常驻服务。共同的NATS/Taskiq启用前置与上面的project-stats相同。

| 命令 | 实际工作、结果和完整说明 |
| --- | --- |
| `./run.sh web background-stats` | 两次真实SQL采样、running/stopped、取消finally；[后台工作](background-work.md) |
| `./run.sh web python-process` | 顶层函数在spawn子进程统计项目；另有error/timeout/cancel模式及PID回收；[后台工作](background-work.md) |
| `./run.sh web subprocess-demo` | 固定外部程序的stdin/stdout、非零退出、超时/取消、进程组清理；[后台工作](background-work.md) |
| `./run.sh web worker-demo` | 固定Worker实际写出项目快照后确认结果，另有error/stop；[后台工作](background-work.md) |
| `./run.sh web cache-levels` | Memory与TwoLevel命中/TTL、另一个进程更新Redis后本地副本仍旧；[缓存教程](cache-and-http.md) |
| `./run.sh web django-cache` | 与真实Django backend双向读写；先按教程隔离安装可选Django，不加入生产依赖；[缓存教程](cache-and-http.md) |
| `./run.sh web image-cache` | 自有PNG/WebP、独占Storage、命中续期和下次写入清理；[缓存教程](cache-and-http.md) |
| `./run.sh web cached-stats` | 同一SQL函数的缓存命中与真实过期；[缓存教程](cache-and-http.md) |

按上述详细教程准备数据库及需要的Redis别名；ImageCache不查数据库。命令只写自己的临时报告、随机缓存键和临时文件，结束负责清理，不修改项目记录。错误模式是有意演示失败，不能把预期非零退出当作正常成功，也不要在用户真实资源中制造故障。

## Redis 缓存

`/examples/cache/redis` 使用已有 ExampleProject 数据：上方三个按钮分别读取统计、重新计算和清除单 key。首次未命中查数据库，之后共享 30 秒 JSON 快照；读取命中不延长 TTL，也不查询项目表。空表显示零项目，GET 页面不提前加载统计，不写入项目数据。

同页下方另有HTTP响应缓存：GET `/examples/cache/response` 将整份JSON动作响应缓存5秒，POST同路径主动失效后重新读取会产生新计算时间。它与上方统计值缓存独立；先验证staff，再按当前语言缓存，POST保留CSRF，不能把缓存当成绕过权限的入口。

完整操作顺序、共享数据边界和失败提示见[缓存教程](cache-and-http.md)。源码为 [cache_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/cache_example.py)、[views/cache.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/cache.py) 和 [cache 模板目录](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/cache)。它复用普通 ExamplesPage，不是新增的前端缓存组件。

## 后端 HTTP

`/examples/http/client` 通过 Python MultiHttpClient 请求可配置的 httpbin 上游，四个按钮展示 JSON、上游 404、超时和逐块读取。只在点击时联网，不转发登录 Cookie 或数据库记录；不会把上游失败画成成功，也不会把上游 404 当作 Demo 路由不存在。

操作、第三方访问说明和错误边界见[HTTP 教程](cache-and-http.md#运行后端-http-示例)。源码为 [http_example.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/http_example.py)、[views/http.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/http.py)、[App 设置](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/settings.py) 和 [HTTP 模板目录](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/http)。客户端由真实 WebService 初始化/关闭，页面复用 ExamplesPage；没有新后台服务或 HTTP 专用 TS。

## 服务通信

先按[通信教程](service-communication.md)准备配置、数据库并分别启动 nats_a、nats_b 和 Web。`/examples/communication/rpc` 查询指定节点的真实项目数据/PID，并可发布报告；`/examples/communication/events` 手动发送竞争/广播事件及查询两节点计数；`/examples/communication/failures` 实际展示无响应者、超时和接收异常。事件计数只在接收进程内，重启归零，不制造数据库记录。

源码为 apps/examples/nats_messages.py、nats_example.py、views/communication.py、apps/communication/events.py、services/nats_a.py/nats_b.py 和 templates/pages/examples/communication/。页面共用普通 Form/Actions、staff/CSRF；只操作固定目标和业务记录。任务页 `/examples/tasks/results` 的 project_rpc 另外展示 Taskiq 执行进程内调用同一共享 RPC 函数，保留原结果归属检查；不是在浏览器中直接连接 NATS。

## 分布式任务

先按[Taskiq 教程](distributed-tasks.md)配置并分别启动真实 Worker/Scheduler，Web 不代为启动。`/examples/tasks/results` 展示数据库摘要、Storage 导出、失败和结果查询；`/examples/tasks/schedules` 展示到期、取消、固定/动态周期和重试；`/examples/tasks/queues` 展示队列共享并发、在线广播和条件 UPDATE 的重复效果。

源码为 [tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tasks.py)、[views/tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tasks.py)、[任务模板](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/tasks)以及 services/task_worker.py、services/task_scheduler.py。数据复用 ExampleProject/ExampleTask，不建立任务历史模型；页面 GET 不发布。结果/调度 ID 先验证当前用户归属，浏览器只操作固定业务白名单。

## 表格和数据操作

共同源码：[models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py)、[tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py)、[views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py)、[表格模板目录](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/tables)。完整讲解见[Table/Modal 教程](tutorial-dashboard.md)。

| 页面 | 可以操作或核对什么 |
| --- | --- |
| `/examples/tables/static` | 首次 HTML 渲染的真实项目数据；不是硬编码行 |
| `/examples/tables/responsive` | 同一数据库的响应式表格布局 |
| `/examples/tables/html`、`/examples/tables/json` | 同一查询的两种格式；筛选、搜索、分页、排序，以及 Modal 新建/编辑/删除 |
| `/examples/tables/states` | 初始加载、空结果、错误、权限错误的呈现；部分状态由视图显式构造，不代表接口正在真实故障 |
| `/examples/tables/realtime` | 从数据库样本回放 SSE，按行 ID 和列标记局部更新；打开页面不增加监控记录 |
| `/examples/tables/advanced` | **缺口说明**：数据导出、固定表头/列、列显隐、批量操作，不当作已实现 |

实时表格另外看 [realtime-table.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-table.ts) 和 [services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py)。数据库样本回放是展示来源，不是真实采集生产服务器 CPU 的后台服务。

## 表单与输入

字段声明在 [forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py)，普通提交在 [views/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/forms.py)，模板在 [forms 目录](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/forms)。

| 页面 | 实际用途与数据边界 |
| --- | --- |
| `/examples/forms/basics` | 静态控件、HTML 提交、JSON 提交并列；普通字段只校验，不创建项目 |
| `/examples/forms/choices`、`/examples/forms/layouts`、`/examples/forms/validation` | 选择控件、表单布局、字段/整体校验；当前这些页面使用 JSON 提交 |
| `/examples/forms/date-time`、`/examples/forms/masks` | 日期时间与输入格式增强，仍由后端字段校验 |
| `/examples/forms/sliders` | Slider 与表单数值输入联动，不是 Carousel 横向浏览 |
| `/examples/forms/slug`、`/examples/forms/input-spinner`、`/examples/forms/tags` | HTML/JSON 两种提交，并展示服务端清洗后的值；Tags 包含文本分隔和多选标签两类 |
| `/examples/forms/color-picker`、`/examples/forms/rich-text` | HTML/JSON 表单及远程 Modal 中的控件挂载与清理 |
| `/examples/forms/multi-step` | 多步骤的 ExampleProjectForm，两种提交都保存真实项目；不是只有下一步动画 |
| `/examples/forms/json-list` | 不定数量源的增删编辑，使用 JSONListField 在 Text 字段与结构化列表间转换，并保存 ExampleStreamProfile |
| `/examples/forms/selects`、`/examples/forms/autocomplete` | 从数据库搜索 Logo，显示图片和名称、分页加载，保存所选 Logo 关联 |
| `/examples/forms/upload` | 与 Storage 上传页共用同一个模型和保存流程 |
| `/examples/forms/containers` | 在不同容器中放普通 Form，包含远程 Modal，不另设 FormModal |

远程选择另外看 [providers.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/providers.py)、[views/data_inputs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/data_inputs.py)。不要仅复制候选项 HTML 而漏掉服务端选项验证。

Rich Text 示例接收的是 HTML 内容；是否允许发布、如何处理不可信内容仍由应用后端决定。普通演示提交成功不等于内容已经保存到数据库或允许公开渲染。

## 容器、动作和生命周期

| 页面 | 源码与重点 |
| --- | --- |
| `/examples/modals/basics`、`/examples/modals/remote` | [views/modals.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/modals.py)：普通容器、远程 parts、内容变化 |
| `/examples/modals/workflows` | 同一 Modal 内按步骤提交和替换内容，新的普通 Form 重新挂载 |
| `/examples/modals/actions` | 五种内置动作、`example_mark` 私有动作，以及缺失目标/未知动作/中途失败的显式演示 |
| `/examples/navigation/lifecycle`、`/examples/navigation/actions`、`/examples/navigation/loading` | [views/navigation.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/navigation.py)、[navigation-probe.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/navigation-probe.ts)：切页、加载与旧资源释放 |

页面类为 [ExamplesPage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts)。私有动作由它的 `handleResponseAction()` 处理；框架内置动作仍走共享 Runner。离开页面时丢弃旧 UI 工作，不等待动作全部完成才允许导航。

## 消息、通知、身份与语言

| 页面 | 源码与重点 |
| --- | --- |
| `/examples/messages/page` | [views/messages.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/messages.py)：Cookie 一次性页面提示，不写通知中心 |
| `/examples/messages/feedback` | toast/alert/message 兜底，以及 confirm 审核、prompt 改名的真实项目写入；[操作与失败边界](components.md#确认和输入实际修改项目)，不是静态成功提示 |
| `/examples/notifications/generator`、`/examples/notifications/realtime` | [views/notifications.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/notifications.py)：主动发送持久/临时通知；发送会产生实际效果，不是静态预览 |
| `/examples/notifications/center`、`/user-notifications` | 同一用户的数据库通知记录及共享通知中心 |
| `/examples/auth/login`、`/examples/auth/guards`、`/examples/auth/identity` | [views/auth_session_i18n.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/auth_session_i18n.py)：认证、权限、当前身份 |
| `/examples/session/lifecycle`、`/examples/session/revoke`、`/examples/session/expiry` | 同一视图模块；撤销和过期按钮会改变真实 Session，操作后可能需要重新登录 |
| `/examples/i18n/server`、`/examples/i18n/browser`、`/examples/i18n/coverage` | 服务端与浏览器翻译、当前语言覆盖情况；不能只改 html 的 lang 属性 |

壳上的用户 SSE 路由在 [apps/auth/views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/views.py)，初始化在 services/web.py；不要为通知再创建第二个专用订阅系统。

## 文件、图表与拖拽

| 页面 | 源码与重点 |
| --- | --- |
| `/examples/storage/upload`、`/examples/storage/lifecycle` | [views/storage.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/storage.py)：两个文件字段、替换、清空预览、删除记录及失败边界；会改变真实文件 |
| `/examples/storage/api` | services.py 的 `run_storage_api_demo()`：实际保存、打开、查询和删除文件 |
| `/examples/sortable/workflow` | [views/sortable.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/sortable.py)：移动 ExampleTask 并持久保存状态和顺序 |
| `/examples/charts/trends`、`/examples/charts/composition`、`/examples/charts/distribution` | [chart_views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/chart_views.py)、[views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py)：数据库聚合与不同图表类型 |
| `/examples/charts/states` | 加载、空数据、错误、权限状态，不把演示错误当成随机故障 |
| `/examples/charts/realtime` | [realtime-chart.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-chart.ts)：SSE 更新；显式发布按钮会写监控样本，与只读表格回放不同 |
| `/examples/data-inputs/lists`、`/examples/data-inputs/autocomplete`、`/examples/data-inputs/providers` | 动态列表、远程选择与 provider 接线，见上面的 forms 和 data_inputs 源码 |

## UI、插件与图标

UI 的具体 HTML 在 [templates/pages/examples/ui/](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/ui)，入口在 [views/ui.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/ui.py)。不要仅凭标题猜 URL：

- 基础视觉：`/examples/ui/foundations`、`typography`、`buttons`、`badges-avatars`、`cards`、`lists`。
- 状态与内容：`/examples/ui/alerts`、`progress-loading`、`timeline`、`images`、`system-states`。
- 交互：`/examples/ui/carousel`、`tabs-disclosure`、`dropdowns-overlays`、`countdown`、`gallery`、`video`、`navigation-shell`。
- 图标：`/examples/ui/icons`，源码 [icons.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/icons.html)；库地址、用法与收集规则同时见[资源参考](../developers/assets.md#图标)。图标页不是把库中全部图标都打进生产 CSS。
- 插件索引：`/examples/plugins`，不是 `/examples/plugins/index`。

上面同一行的短名均沿用开头的 `/examples/ui/` 前缀。这些页面用于验证共享组件与视觉效果；静态 Card/按钮不应为了“可展示”而增加数据库写入或空壳组件。

## 文档取例约束

用户教程、开发者参考和 Agent 指南从上述实际文件取例。摘录必须保留真实符号与路由，并说明所需导入、初始化和消费方；节选应明确标注，不能假装是可独立运行的完整文件。

如果某项能力只有参考接口、Demo 尚无完整场景，先明确缺口并补齐真实示例，再把它写成已可运行的教程。不要另外编一个同名近似接口，也不能为了与文档一致去改动成熟的 Demo 行为。
