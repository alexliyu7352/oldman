# 用户文档

这里面向使用 Oldman 开发应用的人。无需先阅读框架内部实现。

## 顺序学习

1. [运行 EPG Dashboard Demo](getting-started.md)：安装、独立目录、配置、迁移、数据、账户与启动。
2. [Demo 的真实数据](tutorial-tasks.md)：对照实际模型、fixture、迁移与数据库查询。
3. [Demo 的表格与 Modal 表单](tutorial-dashboard.md)：操作现有 HTML/JSON Table，理解登录、表单和增删改链路。
4. [配置、App 与服务](settings-and-apps.md)：多个服务怎样使用不同配置，怎样注册可复用 App。
5. [数据与文件](data-and-files.md)：Demo 的两个文件字段、上传、替换、删除和回滚检查。
6. [缓存与外部 HTTP](cache-and-http.md)：操作真实 Redis 项目统计，以及后端 HTTP 的 JSON、上游错误、超时和流读取。
7. [分布式任务](distributed-tasks.md)：运行真实 Taskiq Worker/Scheduler，操作项目摘要、导出、队列、广播、计划、结果和重复业务效果。
8. [服务通信](service-communication.md)：启动两个真实 Simple 接收服务，操作 NATS RPC、竞争/广播、失败和任务内 RPC。

核心教程直接使用独立 EPG Demo，不另建一套教学业务。每章标明源码文件与节选边界；更多页面见 [Demo 示例索引](demo-examples.md)。在 Demo 自己的环境运行，不在框架源码根目录创建业务文件。需要从零创建空 API 时另看[服务创建指南](../agents/create-service.md)。

## 按问题查阅

- 配置文件不存在、密钥未生成、App 没安装：[配置操作](settings-and-apps.md#创建检查与补全配置)。
- 多个服务使用不同配置：[服务与配置文件](settings-and-apps.md#服务与配置文件)。
- App 需要自己的设置和 IDE 补全：[App 自己的配置](settings-and-apps.md#app-自己的配置)。
- 生成迁移与执行迁移有什么不同：[教程的数据准备步骤](tutorial-tasks.md#3-第一次运行执行已有迁移)。
- 自定义命令和内置命令：[CLI 参考](../developers/cli.md)。
- 基础 UI、下拉、Tabs、Slider、Carousel 与图表：[组件用法](components.md)。
- 表单清洗、动态 JSON 字段、标签和远程选择：[Form 参考](../developers/forms.md)。
- 图标在哪里选、怎样构建样式和翻译：[资源参考](../developers/assets.md)。
- 改名、接管外部表或恢复迁移状态：[迁移参考](../developers/migrations.md)。
- 上传、替换和删除模型文件：[文件存储](../developers/storage.md)。
- 共享缓存、Redis 命名连接、Django 缓存互读：[缓存](../developers/cache.md)和 [provider](../developers/providers.md)。
- 后端调用外部 API、下载流或进行 NATS RPC：[HTTP 客户端](../developers/http-client.md)与 [NATS](../developers/providers.md#nats-连接与发布)。

- 周期工作、计算进程和长期 Worker：[后台工作](background-work.md)。
- 页面提示、通知中心和实时数据：[消息与实时更新](messages-and-live-updates.md)。
- 安装内置管理站点、创建管理员：[Admin](admin.md)。
- 准备生产环境、静态资源及资源关闭：[部署与运行](deployment.md)。

需要了解精确签名和扩展时，再进入[开发者参考](../developers/README.md)。按[示例索引](demo-examples.md)找到具体页面、后端和模板，避免只复制界面而漏掉数据或组件初始化。
