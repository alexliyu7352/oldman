# Oldman 文档

这份文档介绍当前 `oldman` 和 `oldman-web`：是什么、怎样使用，以及怎样扩展。示例不要求了解框架的开发历史。

## 选择阅读入口

| 你现在要做什么 | 从这里开始 |
| --- | --- |
| 第一次用 Oldman 建项目 | [用户文档](users/README.md) |
| 查接口、加载顺序或编写扩展 | [开发者参考](developers/README.md) |
| 让 Agent 根据需求开发应用 | [Agent 应用开发指南](agents/README.md) |

## 常用问题

- 怎样先运行完整示例？读[EPG Demo 运行教程](users/getting-started.md)。从零创建空 API 则看[服务创建指南](agents/create-service.md)。
- 页面上的数据从哪里来？读[Demo 的模型、迁移与查询](users/tutorial-tasks.md)。
- 登录、表格和编辑弹窗怎样连接？对照[Demo 的 Table/Modal 教程](users/tutorial-dashboard.md)。
- 想复制某个现有功能，应该看哪些文件？查 [Demo 页面与源码索引](users/demo-examples.md)。
- 怎样直接使用 UI、图标和交互？读[组件用法](users/components.md)和[资源参考](developers/assets.md)。
- `services`、App 和配置文件有什么区别？读[配置、App 与服务](users/settings-and-apps.md)。
- 为什么提前导入 `settings` 会报错？查[配置参考](developers/configuration.md)。
- 模型、命令和 views 在什么时候加载？查[应用与生命周期](developers/applications.md)。
- 怎样给 App 增加命令？查[CLI 参考](developers/cli.md#自定义-app-命令)。
- 怎样注册自己的请求或响应中间件？查[自定义中间件](developers/web.md#自定义中间件)。
- IDE 的 Python Shell 怎么加载应用？查[调试入口](developers/applications.md#python-shell-与-ide)。
- 怎样直接用内置后台管理模型？读 [Admin 教程](users/admin.md)。
- 缓存结果或调用上游 API 怎样管理连接与失败？读[缓存与 HTTP](users/cache-and-http.md)。
- 本地协程、短进程和固定 Worker 怎样运行及停止？读[后台示例](users/background-work.md)。
- 怎样持久排队、查询任务结果或定时执行？读[Taskiq 教程](users/distributed-tasks.md)。
- 两个后台服务怎样发送事件和 RPC？读[服务通信](users/service-communication.md)。
- 怎样部署和检查资源关闭？读[运行指南](users/deployment.md)。
- 怎样维护、测试和打包框架？读[源码维护](developers/maintenance.md)。

## 示例阅读约定

文中的命令默认在所指 Demo 根目录执行；需要切换目录时会写出 `cd`。核心教程使用 Demo 的真实代码和路由。标为节选的代码依赖原文件的导入及初始化，不是另一份独立程序；源码链接用于对照完整实现，不能用链接省略运行和失败处理说明。

`./run.sh` 是生成项目的便捷入口，参数与 `oldman` 相同。命令中的服务名取自实际 `services/<名字>.py`，不是任意别名。

API 参考负责定义接口；教程与 Agent 指南负责把它们接起来。引用链接指向同一份参考，不以另一套参数或行为解释同一个 API。
