# 任务指南：受保护的 Dashboard CRUD

适用于给现有 Oldman 应用增加列表、新建/编辑 Modal、表单校验和数据库保存。完整可运行基准是 [EPG Demo 的 Table/Modal 教程](../users/tutorial-dashboard.md)，源码是 apps/examples 中的 ExampleProject、ExampleProjectForm、ExampleProjectTable；不要另造 Task 模型或从一个方法节选猜完整服务。

## 先确定本次业务

查看应用 Git 状态、服务入口、本服务 YAML、现有模型和前端入口。确认记录访问范围：所有 staff 共用、按用户，还是按租户。教程明确为 staff 共用，不把 select(Model) 自动当成所有业务正确的查询。

先复用已有 App、模板基类、DashboardPage、数据库 Session 与资源 bundle。添加一个业务页面通常不需要改 settings 结构、安装框架源码或重写 Page/Modal。

最小阅读范围：

- 用[教程](../users/tutorial-dashboard.md)的源码表取得完整接线，按用户业务调整 ExampleProject 场景，而不是改框架公共协议。
- 查[Form](../developers/forms.md)、[Table](../developers/tables.md)和[响应动作](../developers/responses.md)确定字段、查询及返回格式。
- 只有涉及页面、模板或资源初始化时，再看[Web](../developers/web.md)、[Page](../developers/frontend.md)和[资源](../developers/assets.md)对应章节。

## 应用文件如何连接

| 文件 | 要完成的内容 |
| --- | --- |
| `apps/<app>/apps.py` | 唯一 app 元数据；服务 apps 中加入包路径 |
| `models.py`、`migrations/` | 实际模型与标准迁移；不在服务器启动时建表 |
| `forms.py` | TailwindModelForm、Meta.fields 白名单、必要 validator 与 clean 方法 |
| `tables.py` | SQLAlchemyTableView、Column、固定访问范围、搜索和排序 |
| `views.py` | 页面、数据、Modal 初次加载、POST 保存/删除；分别认证授权 |
| `templates/...` | 共享 shell、Table shell、普通 Modal 容器和普通 Form |
| `frontend/src/pages/<entry>.ts` | DashboardPage，完整默认 loader 或明确所需子集 |
| `services/<name>.py` | 仅在尚未具备时接入 Ext、模板、CSRF 和 bundle |
| `data/<name>_settings.yaml` | App、数据库、Session/Redis、模板与静态配置；不提交真实密钥 |

后端 page_entry、body 和主 Frame 的 data-om-page、前端 setupPage 名称一致。共享 `dashboard_main_frame()` 宏会输出主 Frame 入口；自定义模板不能只标记不随 Frame 导航替换的 body。旧页面若已占用相同路由，明确替换或改路径，不能重复注册。纯 HTML 业务页面可共用一个默认 Page 类，仍须启动 loader；切换到另一个业务页面时创建新实例，而不是复用旧 Page。

## 权限和数据库

1. 需要 Session 时启用 settings.web.session，并提供 redis.SESSION。启用 Admin App 不代表已经安装管理站点路由。
2. 页面用 staff_required 等已有装饰器；Table 用 as_view 保留 dispatch。直接调 Table.get 不等价于受保护路由。
3. 每个数据、编辑、保存、删除 endpoint 都单独验证权限。隐藏按钮、不可选字段和签名候选都不替代后端授权。
4. 在 get_queryset 放固定范围；保存前查询属于该范围的模型实例。不能依赖 request.form 主键就直接更新任意行。
5. 写操作用 db_manager.get_session；Form.save(commit=True) 只 add/flush，退出上下文提交成功后才返回成功 actions。只读用 get_read_session。
6. POST 需要 csrf_protect；输出表单的请求生成 CSRF token，并在服务安装 StatelessCSRFManager。不能把“已有 Session”当成“所有 POST 自动有 CSRF”。

编辑 `instance=...`；fields 只列允许用户修改的业务字段。没有文件字段时不引入文件生命周期代码。有上传时先查看现有 Storage 和 ModelForm 文件支持，不能把 commit=False 当成无文件写入。

## 响应选择，不能混用

| 请求 | 后端返回 | 消费方 |
| --- | --- | --- |
| 完整页面/原生提交 | HTML；原生提交失败仍是 HTML | 浏览器导航 |
| Modal 第一次载入 | Demo 返回 title/html；通用 parts 也有 body/footer 字段，详见 Modal 参考 | Dashboard Modal.loadParts |
| JSON Form 保存 | HTTP 200 DefaultApiFormResponse；字段错误、message、有序 actions | 普通 Form 和 Page Runner |
| HTML Form 保存 | 2xx HTML 或 422 错误表单 HTML | Form 内部统一处理 |
| Table 数据 | HTML 片段或专用 columns/rows/pagination/sort JSON | Table |
| 通用 data-om-action | 2xx DefaultApiResponse | 当前 Page Runner |

保存成功通常返回 ReloadTableAction、CloseModalAction 和 FeedbackAction；明确指定 Table target。不要又在 om:form:success 写第二次刷新。message/errors 在 actions 前显示，状态事件在 actions 后；Form 已被替换就不更新旧实例。

replace_html 解析目标顺序为 action.target → 请求元素 data-om-target → 请求元素自身；swap 为 action.swap → data-om-swap → inner。需要替换一块具体区域时显式指定目标，避免无意替换按钮本身。多区域通过多个动作顺序表达，响应顶层不另设 HTML 更新字段。

业务 error_code 不自动重试，也不阻止 actions。401/403/5xx、断网与超时交给公共 HTTP 错误链路；动作异常停止后续动作并显示全局 Feedback，不能把异常伪装成表单字段错误。

## 浏览器职责

使用 DashboardPage 与 createDashboardComponentLoaders；Modal 内的表单仍是 form loader，不另写一套 Modal 表单提交。通过 Table/Modal/replace_html 的已有生命周期替换 HTML，不能裸 innerHTML 后忘记卸载和挂载。声明式远程 Modal 失败由共享点击入口使用所属 Page 的 Feedback 提示，离页取消不提示；不再添加重复的 om:modal:error 弹窗监听器。直接调用 loadParts/loadContent 仍由调用方捕获原异常。验证首次加载失败时的可见反馈、再次打开成功与离页取消；具体能力见[Modal 参考](../developers/frontend.md#modal-只是容器)。

业务需要私有动作时覆盖异步 handleResponseAction(action, context)，返回 true 表示处理；false 让 Runner 报未处理。请求使用 page.http，监听、timer 和订阅通过 Page 登记释放。页面离开时放弃旧 UI 工作，不增加全站导航锁或 Prefetch。

私有 loader 放在对应的业务 Page。验证必须包含“从另一个 Page 通过侧栏进入”，不能只直接打开 URL；参考 EPG Demo `frontend/src/pages/examples.ts` 中的私有组件和 `example_mark` 动作。若直接打开正常而侧栏进入失败，先检查主 Frame 的入口标记、旧 Page 是否卸载、新 Page 是否创建，不要把所有组件移到全局。Form/Table/Modal 的局部内容更新则不应销毁当前 Page。

表格实时字段可用 data-om-table-row-id 与 data-om-column 定位；当前没有 updateCell 公开接口。直接写 DOM 只改显示，不更新数据库或 JSON Table 内部数据。没有用户实时需求就不增加 SSE。

## 执行与验证

需要“先确认/输入，再调用业务接口”时，使用 EPG `/examples/messages/feedback` 的真实流程，不另造弹窗系统。复制接线时核对这四处：`views/messages.py::example_feedback_project`、`templates/pages/examples/messages/feedback.html` 及结果片段、`components/examples/feedback-workflow.ts`、`pages/examples.ts` 私有 loader。具体代码及类型来源见[Feedback 交互](../developers/frontend.md#feedback-交互与真实请求)。

这个表单只保存请求参数，不挂普通 Form loader；按钮不自动提交，取消不发 POST。已有 Page Feedback 经过类型收窄后调用 confirm/prompt，确认分支显式开启取消按钮，输入分支检查 isConfirmed。确认后检查组件 signal，再使用现有 preloader.withLoading/runAction；finally 恢复按钮。后端权限、CSRF、输入与记录校验不可省略，写事务成功退出后才返回成功动作。离页取消 UI，不保证撤销已经提交的数据。不要把 confirm/prompt 增加到内置 Actions，也不要为它创建全局 Feedback 或私有 HTTP Client。

在应用项目内按顺序完成：

1. 设置同步/检查；新增模型时生成并检查迁移，再单独 db migrate。命令是项目级 db，不是 `<service> db`。
2. 安装应用 frontend 依赖、生成图标和必要翻译、typecheck、build。Vite 使用 SCSS 时显式安装 sass，不依赖 pnpm 偶然提升。
3. 使用该服务的 run.sh 命令启动，确认不是另一个残留 Demo 占用端口。不要改 run.sh 自动启动多个服务。
4. 用真实 Chrome 操作未登录、有效登录、空值/业务校验失败、新建、编辑、删除确认、取消 Modal、两种 Table 模式和返回页面。检查数据库实际变化，不能只看 toast。
5. 最少验证当前任务的一条失败路径：未授权记录不可写；保存失败无成功动作；服务器不可用后加载结束且有提示。不用为单页任务并发运行全项目门禁。
6. 查看 console、失败请求及生成资源；退出后确认自己启动的进程已停止。临时项目、账户和数据只放自己的 /tmp 目录并清理，不改用户 Demo 数据。

交付说明列出真实地址、准备命令、验证结果及未完成范围。文档未覆盖或运行版本不同的地方再定向查实现，不凭经验发明 get_current_page、updateCell、全局 MessageBus 或第二套配置代理。
