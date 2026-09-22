# 发行说明

## 0.2.0 —— 2026-09-22

浏览器包与 Python 包同步更新。含破坏性变更,次版本号相应抬升。

### 破坏性变更

- **浏览器翻译属性改名**：`data-key` → `data-om-i18n-key`。框架不再认领 `[data-key]` 这个无前缀的全局选择器——那个名字属于使用它的应用。**没有兼容层**：请在模板里直接改名，`oldman-web` 不会再查 `[data-key]`。

### 新增

- **邮件**：形如 `django.core.mail` 的异步外发层，按收件人语言渲染模板，配 `mail sendtest` 服务命令与 SMTP 往返测试。
- **密码重置**：令牌、按邮箱查找、专用设置与速率限制，`PasswordResetFlow.register_routes` 一次装好六个视图。
- **浏览器指纹**：可选子系统，浏览器一半与服务端一半配套；是「可用」而非「必开」。
- **认证脱离 Admin**：用户表单与管理规则、共享用户表格、状态与删除弹窗、登录步骤和 `safe_next_url` 移入 `oldman.web.auth`，不安装 Admin 也能用。
- **表格**：工具栏（选中计数、批量动作槽、列菜单、密度）、经数据端点的 CSV 导出、吸顶表头、表内空状态与筛选重置、行内筛选条、共享单元格原语与 `RowAction`。
- **表单**：布尔控件、`FieldGroup`、列级标签、`before_save` 钩子、远端 Select 自己拥有初始选项、`EmailField` 每个地址只存一种写法。
- **国际化**：框架自己构建浏览器目录与语言清单；配置了某语言却没有目录时拒绝启动。
- **测试门禁**：浏览器、进程树与 PNG 门禁助手，通知与资源归属两个浏览器门禁，以及可当普通测试跑的重复实现守卫。

### 修复

对 16,929 行前端生产代码做了逐行审查，23 条缺陷在本段全部清零。主要几条：

- 标记写错的组件不再拆掉兄弟组件——每个组件独立挂载，只把自己标成 `failed`。
- 框架此前认领的无归属全局选择器收回到各自的作用域内。
- HTTP 客户端会注销它挂在长生命周期作用域信号上的监听器。
- 页面卸载不会卡住下一次导航（默认 5 秒超时，超时后照常恢复并报错）。
- 关闭途中被销毁的 Modal 会执行完这次关闭，而不是取消它。
- 嵌套的作用域 preloader 不再互相吞掉遮罩。
- 携带链接的响应动作拒绝会执行的协议（`javascript:`、`data:`），同时仍然放行正常的站外 https 目标。

另有 HTTP 客户端的会话生命周期修复：`reset_client` 关闭失败时也会丢弃会话，不再把一个关不掉的会话留下来复用。

### 验证

ruff、pyright、1974 项 Python 测试、oldman-web 与 admin 两套前端测试，以及边界、打包和脚手架矩阵检查全部通过；两个 Demo 应用上另做了真实 Chrome 验收。

## 0.1.1 —— 2026-09-14

- 新增 GitHub Actions 的验证与发布工作流；Redis 集成测试自带服务实例，不再依赖 CI 环境预置。
- 发行产物检查接受规范化后的预发布版本号与超长路径的 PAX 头。
- 流式 HTTP 响应提前退出时，迭代器链按确定顺序关闭。

## 0.1.0 —— 2026-09-14

首个发行版本同时提供 Python 包 `oldman` 与浏览器包 `oldman-web`。

### 主要能力

- 服务级 YAML 配置、App 注册、CLI、项目脚手架、IDE/Shell 初始化，以及 Web、Simple、Worker 和 Scheduler 生命周期。
- SQLAlchemy 模型与 Alembic 迁移入口、JSON fixture 导入导出、文件存储、缓存与公共 HTTP 客户端。
- 用户认证、Redis Session、CSRF、可覆盖的错误模板、Cookie 一次性消息和持久通知。
- 服务端 HTML 表单、异步校验、ModelForm、文件上传，以及统一的有序 JSON 响应动作。
- 共用组件和 DOM 协议的 Admin/Dashboard；HTML/JSON Table、Modal、选择与输入增强、图表、图标和中英文界面。
- 浏览器 SSE 投递；Core NATS/FastStream 的事件与 RPC；Taskiq 的持久任务、结果、定时计划及 Worker 管理。这三种用途使用各自明确的接口。

具体用法见[用户文档](docs/users/README.md)、[开发者参考](docs/developers/README.md)及[Agent 指南](docs/agents/README.md)。可操作示例来自独立的 Admin Demo 与 EPG Dashboard Demo，入口见[Demo 索引](docs/users/demo-examples.md)。

### 本轮验收中修复

- NATS 订阅启动结束前确认服务器已收到订阅，避免另一连接紧接着 RPC 时偶发找不到接收者；普通发布路径不增加往返。
- TLS 重连拒绝明文端点时关闭该连接，避免旧 socket 被覆盖后只能等待垃圾回收。仍拒绝明文发送凭据。
- Dropdown、Popover只处理自身的Escape，不再抢走从菜单打开的Modal的关闭按键。
- 修正多选标签 Widget 的类型标注及前端公开组件的类型路径。过时门禁按真实运行协议修正，不恢复旧接口。

### 使用范围与部署提醒

- Linux；Python 3.12/3.13；Node.js 20 及以上；应用使用 Tailwind CSS 4。框架开发锁定 pnpm 9.12.3。
- Python/npm 版本须配套。应用部署需要自己的依赖锁、实际连接配置、迁移和静态资源收集，不能用源码关联替代发行包部署。
- 分布式任务不承诺绝对只执行一次；确认丢失、Worker 中途退出等具体情形及业务处理见[任务文档](docs/users/distributed-tasks.md)。
- Chrome 是本轮实际验收浏览器，不代表其他浏览器被禁止。未执行的数据库、浏览器和生产容量验证不能由单元测试结果代替。
- MIT 许可及随包第三方许可文件保留；具体部署仍须审阅应用自己的依赖和资源许可。

部署前见[运行指南](docs/users/deployment.md)。
