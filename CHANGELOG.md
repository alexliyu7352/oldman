# 发行说明

## 0.1.0 — 待发布

首个发行版本同时提供 Python 包 `oldman` 与浏览器包 `oldman-web`。当前仍是本地发布候选，尚未上传包索引；实际发布使用通过验收的同一组 wheel、sdist 和 npm tarball。

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

发布候选的准确源码提交、产物 SHA-256、实际检查结果与未验证边界见[本轮验收记录](docs/internal/2026-09-11-release-candidate-acceptance.md)。部署前另见[运行指南](docs/users/deployment.md)。
