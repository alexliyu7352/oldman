# 局部代码片段

本目录不是可直接安装启动的 Demo，不包含完整项目配置和数据准备。只用于观察小段代码的写法：

- `cli_app/main.py`：普通 Python 命令入口，不是 App Command 注册示例。
- `app_service/services/example_worker.py`：后台服务类片段，缺少完整服务项目。
- `web_service/`：视图、表单和模板片段，不能假定其中每个跳转目标都有对应路由。

新项目在准备存放应用的父目录执行：

```sh
oldman startproject my_project
```

按交互选择 cli、service、api、web 或 dashboard 及适用的数据库选项；不使用 --type 参数。生成后进入项目，按其 README 安装、配置并运行具体服务。

需要可以逐步运行的完整代码，使用[EPG Demo 入门](../../docs/users/getting-started.md)、[数据库教程](../../docs/users/tutorial-tasks.md)、[Dashboard 教程](../../docs/users/tutorial-dashboard.md)或 [Admin 教程](../../docs/users/admin.md)。从零创建空 API 另看[服务创建指南](../../docs/agents/create-service.md)。完整 UI Demo 是根 [README](../../README.md)中链接的独立项目。

不要为了尝试这些片段而在框架根目录新增业务 config、services、数据库或虚拟环境。
