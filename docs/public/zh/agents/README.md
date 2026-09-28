# Agent 应用开发入口

本目录帮助 Agent 在没有历史对话的情况下，使用当前 Oldman 开发应用。它不是另一份框架 API 定义，也不要求先通读整个源码仓库。

## 按任务进入

| 任务 | 阅读与交付 |
| --- | --- |
| 新建 API 或后台服务 | [创建服务指南](create-service.md)，完成配置、App、入口和实际请求或命令验证 |
| 给服务增加持久数据 | [Demo 数据教程](../users/tutorial-tasks.md)，对照 ExampleProject 的模型、迁移与事务接线 |
| 给 App 增加配置 | [配置参考](../developers/configuration.md#app-settings)，直接导入该 App 的强类型实例 |
| 增加项目命令 | [Command 合同](../developers/cli.md#自定义-app-命令)，使用 Registry 已有发现机制 |
| 处理初始化或导入错误 | [加载顺序](../developers/applications.md#实际加载顺序)，区分配置、模型与 Web 阶段 |
| 开发 Dashboard CRUD/Modal Form | [接线指南](dashboard-crud.md)，覆盖权限、数据库、两种 Table、响应和浏览器验证 |
| 添加现有 UI 或字段增强 | [组件用法](../users/components.md)与[字段参考](../developers/forms.md)，复用当前 loader/Widget |
| 构建应用样式、图标及翻译 | [资源参考](../developers/assets.md)，在应用工程安装和构建，不复制框架产物 |
| 修改模型、准备 fixture 或接入文件 | [数据与文件指南](data-and-files.md)，核对迁移范围、事务和文件生命周期 |
| 缓存、请求上游或使用 Redis/NATS | [缓存与网络指南](cache-and-network.md)，选择现有客户端、配置隔离、管理连接与失败 |
| 接入服务间事件/RPC | [通信教程](../users/service-communication.md)及[接线清单](cache-and-network.md#nats按真实-demo-接线)，对照接收 App、共享消息、配置和真实进程 |
| 执行后台工作或外部程序 | [后台任务指南](background-work.md)，按进程寿命选择接口，验证执行结果与退出 |
| 将异步工作交给持久队列/定时执行 | [Taskiq 接线](distributed-tasks.md)，对照 Demo 配置、任务、服务、权限和真实运行 |
| SSE 更新 Table 或接入通知 | [实时页面指南](realtime.md)，复用稳定 DOM、请求权限、用户连接和持久通知 API |
| 接入管理站点或扩展 ModelAdmin | [Admin 指南](admin.md)，区分 App 注册、模型管理与路由安装 |
| 准备应用部署 | [部署指南](../users/deployment.md)及[安全边界](../developers/security.md)，核对真实依赖、权限与关闭责任 |
| 维护框架与验证产物 | [源码维护](../developers/maintenance.md)和[测试隔离](../developers/testing.md)，不混进业务开发任务 |

## 开始前只确定必要信息

确认工作对象是应用仓库还是框架仓库，并查看 Git 状态、项目 `pyproject.toml`、`services/` 和本服务 YAML。不要把业务代码写进安装的 `oldman` 包。

已有应用优先使用现有服务、App、数据表和公共组件；新建内容以前先查它是否已经存在。实现用户请求的那个能力，不顺手改其他模块。

需要示例时先查 [Demo 页面与源码索引](../users/demo-examples.md)。引用真实类名、路由和 DOM 标记，说明节选依赖；不再另造一套教学业务。Demo 尚无可运行场景时先报告缺口，不能只用参考接口拼出代码就声称已在 Demo 验证。

需要用户作出的实际选择包括：服务用途、是否公开访问、数据库、哪些 App 要安装、接口的数据范围。密码和连接信息由用户在运行配置中填写，不写进示例提交。

## 不依赖历史上下文的固定事实

- Python 包是 `oldman`，浏览器包是 `oldman-web`。普通 API 或后台服务不需要为此编译前端。
- 服务名由 `services/<name>.py` 决定，配置默认是 `data/<name>_settings.yaml`。
- 每个服务进程只有一个根 Settings 实例；项目只定义一种根 Settings 类型。
- `settings.apps` 是显式包路径列表。每个包的 `apps.py` 导出唯一的 `app` 对象。
- App Settings 从 `app.settings` 读取；不会动态成为全局 Settings 的属性。
- `bootstrap_service()` 负责配置与模型的统一初始化。不要添加第二套 setup 或让模块 import 自动启动服务。
- 模型在 Registry 的模型阶段声明；业务 views、命令可以导入已经加载的模型，但不能在自己的模块中另行声明表。
- 数据库结构通过项目级 `oldman db ...` 管理，服务启动不自动迁移。
- 模板、表单和 Table 的服务端实现属于 `oldman.web`，浏览器交互属于 `oldman-web`。Admin 与 Dashboard 不维护两套公共实现。

## 最小交付检查

1. 列出新增或修改的应用文件，代码中的 helper 要么在示例中定义，要么使用真实公开导入。
2. 说明怎样注册 App、补全配置和准备必要数据。只创建子类而没有加载入口不算完成。
3. 运行当前任务需要的命令或请求，检查真实结果和一条有代表性的失败路径；不为一个小功能跑全项目门禁。
4. 说明写入何时提交、异常由谁处理、连接或后台任务由谁关闭。
5. 涉及前端交互时用真实浏览器操作，不把源码字符串断言当作视觉验收。
6. 保留用户修改；不提交密钥、数据库、虚拟环境、依赖目录或本次临时文件。

这些规则不授权删除用户数据、重置工作区或启动子 Agent。框架仓库的修改还须遵守该仓库自己的贡献约定。
