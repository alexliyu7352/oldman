# 开发者参考

这里定义公开入口、加载顺序和扩展合同。首次建项目可以先看[用户教程](../users/getting-started.md)，不用先读完全部参考。

| 主题 | 内容 |
| --- | --- |
| [应用与生命周期](applications.md) | 服务发现、AppConfig、Registry、Web/SimpleApplication、Shell 和资源归属 |
| [配置参考](configuration.md) | 根 Settings、App Settings、YAML 管理、默认值和配置路径 |
| [CLI 参考](cli.md) | 项目与服务命令、交互约定、自定义异步 Command |
| [Web 请求与模板](web.md) | 路由、模板加载、Session、权限、CSRF 和错误页 |
| [表单与字段](forms.md) | WTForms 分工、绑定/校验、ModelForm、布局、远程选项 |
| [Table](tables.md) | HTML/JSON 数据、数据库查询、列路径、排序和稳定 DOM |
| [Chart](charts.md) | data endpoint、外壳、请求白名单、时间窗口和结果对象 |
| [响应协议](responses.md) | JSON/Form/HTML 边界、有序 actions、目标和错误处理 |
| [浏览器生命周期](frontend.md) | Page、组件、Modal、动态挂载、HTTP 和导航清理 |
| [资源与样式](assets.md) | Vite、bundle、字体、图标、视觉变量和统一翻译 |
| [模型与数据库](database.md) | 映射、会话、事务、查询、User 外键和连接关闭 |
| [数据库迁移](migrations.md) | 项目范围、App 分支、改名、外部表、降级和状态恢复 |
| [JSON fixtures](fixtures.md) | 服务级导入导出、字段类型、外键顺序和失败边界 |
| [文件存储](storage.md) | alias、异步读写、文件字段、替换/删除与私有下载 |
| [邮件](mail.md) | 消息对象、后端、模板邮件、locmem 测试与 `mail sendtest` |
| [缓存](cache.md) | 内存/Redis/两级缓存、TTL、响应缓存、Django 互操作和图片缓存 |
| [Redis/NATS provider](providers.md) | 命名连接、锁、受管 bus、强类型事件/RPC、寻址与完整启停责任 |
| [后端 HTTP 客户端](http-client.md) | 三种 backend、统一响应、重试、流、Cookie 与 TLS |
| [进程与后台任务](background.md) | 协程、短期进程、受控外部命令、长期 Worker 与可靠性限制 |
| [分布式 Taskiq 任务](distributed-tasks.md) | 原生任务 API、JetStream/Redis、Worker/Scheduler、结果与确认失败边界 |
| [日志](logging.md) | 标准 Logger、初始化、文件轮转、子进程和关闭 |
| [消息与通知](messages.md) | Cookie 提示、Form/Feedback、数据库通知和共享顶栏/中心 |
| [SSE 与 WebSocket](sse.md) | 直接输出、Redis 发布、Session、翻译、背压与浏览器连接 |
| [Admin](admin.md) | 显式站点安装、ModelAdmin、权限、模板和资源扩展 |
| [安全与限流](security.md) | 统一密钥、信任边界、Redis 限流与指纹工具的实际职责 |
| [源码维护与发布](maintenance.md) | 构建、版本、串行验收、安装产物和证据清理 |
| [测试隔离](testing.md) | 配置、App、模型、进程和数据库的测试边界 |

参考中的类与函数使用安装包公开导入。私有方法只在解释调用顺序时提及，不作为应用开发入口。

扩展时先确定代码属于服务、App 还是单次请求。服务负责启动和资源；App 提供业务模块；视图处理请求。不要通过在导入阶段创建 Application、连接数据库或加载 views 来绕过正常初始化。

完整消费场景从 [Demo 页面与源码索引](../users/demo-examples.md)进入，再按各主题查精确 API。示例应取自对应 Demo 文件并标明节选及依赖；ExampleProjectForm 等是 Demo 业务类，不是框架公开 API。若文档没有覆盖某个高度定制的行为，再定向检查该接口的实现。
