# 为应用接入 Admin

适用于用户要管理已注册数据库模型、创建管理员或扩展管理表单。不适用于把任意业务页面硬塞进 Admin，或假定框架会自动实现租户隔离。

## 最小阅读与文件范围

先读[用户 Admin 步骤](../users/admin.md)，它使用独立 Admin Demo 的 YAML、DemoProject、DemoProjectAdmin、服务文件和实际命令；不是 EPG 的业务用户页面或另造的 Task 项目。再按需要读 [ModelAdmin 参考](../developers/admin.md)，不需要读框架历史设计。

通常只修改：

1. 当前服务的 `data/<服务名>_settings.yaml`：App、Session/Redis、模板、静态配置；真实秘密不提交。
2. 已安装业务 App 的 `admin.py`：定义 ModelAdmin，不在这里重定义模型。
3. 现有 `services/<服务名>.py`：显式导入 ModelAdmin 和模型，在 super().init() 后创建/注册站点并 install_admin。
4. 确有覆盖需求时才增加项目 `templates/admin/...` 或应用 CSS bundle。

已有 Dashboard 服务时保留其前端和模板接线，在末尾添加 Admin；不要用教程的最小服务覆盖真实业务逻辑。只要求创建账户时，执行 Admin App 命令即可，不必安装站点路由。

## 必须保持的接线

- `oldman.auth`、`oldman.apps.admin` 都须在这个服务显式安装。App 注册不会自动安装 `/admin`。
- Session 显式开启，使用当前服务的 Redis alias；不创建生产 Memory Session。
- `install_admin` 默认取得配置选定的 User、全局数据库管理器和 App Settings。通常只传 app、admin_site 和必要 prefix。
- 业务模型通过 `site.register(Model, ModelAdminSubclass)` 注册；User 的定制继承 AdminUserModelAdmin，不能用普通管理器暴露 password_hash。
- 配置只从根单例或对应 App 的 app.settings 读取，不设置 app.ctx.settings。
- 所有表通过 db migrate 准备，所有内置静态文件通过本服务 static collect 准备；不在启动时创建表或写默认密码。
- 需要预设项目时参考 Admin Demo 的 apps/demo/fixtures/demo.json，以 web loaddata demo 显式导入；不把验证脚本的固定账号复制进服务。重复导入按主键更新，普通重启不会补回删除的行、覆盖字段或重置用户。旧数据库已有测试账号由用户处置，不能自行删除真实记录。
- 保存/删除钩子使用传入的 AsyncSession；外层事务负责提交，不能在钩子中另开提交。

## 验证实际结果

先检查服务命令帮助中出现 createsuperuser/changepassword。执行配置检查和迁移，在用户授权的数据库创建测试账户，不改真实账户密码作为测试。

浏览器访问实际 prefix：验证未登录跳转、正确和错误密码、App 一级菜单、模型显示名、真实列表查询、新建/编辑/删除，以及一条字段校验失败。验证失败时数据库没有新增记录；不要只检查模板中含某个字符串。

增加自定义 CSS、图标或模板后要真正构建/收集，再打开 Chrome 检查；源码中写了 class 不代表构建产物含它。未启用通知时不要为填空而生成假通知，启用时沿用[实时接线](realtime.md)。

交付注明使用哪个服务、测试地址、数据库变更、账户由用户如何创建，以及是否需要重新 collect。部署要求见[运行指南](../users/deployment.md)。
