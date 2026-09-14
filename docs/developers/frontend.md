# Page、组件与动态内容

`oldman-web` 是原生 TypeScript 浏览器包，不要求 React/Vue。后端 HTML 声明页面和组件，入口启动运行时，组件管理器负责挂载与清理。安装与构建见[资源和样式](assets.md)，真实 CRUD 接线见 [EPG Demo 的表格与 Modal](../users/tutorial-dashboard.md)。

## Demo 的 Dashboard 页面入口

实际入口是 [EPG frontend/src/main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts)，不是每页各自调用一次 startOldman。该文件先创建公共 HTTP Client 和 i18n，建立 OldmanContext，等待语言初始化，然后调用 `startOldman({ context, pageLoader: loadPageEntry })`。

页面模块列表原文：

```typescript
const pageEntries = import.meta.glob([
  "./pages/backend.ts",
  "./pages/examples.ts",
  "./pages/login.ts",
  "!./pages/**/*.test.ts"
]);
```

同一文件中实际的 loader：

```typescript
async function loadPageEntry(pageName: string): Promise<void> {
  const loader = pageEntries[`./pages/${pageName}.ts`];
  if (!loader) return;

  await loader();
}
```

这些是 main.ts 的节选，完整文件还包含 CSS 导入、context 和语言资源地址初始化，以及启动异常处理。直接使用 Demo 的完整入口，不把两个节选拼成缺少依赖的“最小 main.ts”。

普通业务页在 [backend.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/backend.ts) 中继承项目 BasePage，并执行 `setupPage("backend", BackendPage)`。示例页则在 [examples.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) 注册 `setupPage("examples", ExamplesPage)`，提供自己的 loader 和动作。

服务端通过 `page_entry="examples"` 指定示例入口。共享模板在 body 和 `dashboard_main_frame()` 输出的主 Frame 上标记同一页面名；不能只标记不会随 Frame 导航改变的 body。setupPage 注册构造器，PageRegistry 才创建页面实例。

项目 [base-page.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/base-page.ts) 中的 BasePage **是应用自己的类**，继承框架 DashboardPage；不要与 `oldman-web/app` 导出的框架 BasePage 混为一谈。它合并共享 Dashboard loaders 和应用覆盖项。纯 HTML 业务页仍需要这个公共运行时来挂载组件，不需要另写一份私有 Page 逻辑。

完整资源和翻译接线见[资源参考](assets.md)，在 Demo 直接打开页面与侧栏进入页面都应该经过上述入口。不要把私有 loader 搬到全局来补救 Page 没有切换。

## 三层对象的职责

| 对象 | 来源与职责 |
| --- | --- |
| `OldmanContext` | `createOldmanContext()` / `getOldmanContext()`；共享 i18n、HTTP、日志、资源地址和注册表 |
| `Page` / `BasePage` / `DashboardPage` | PageRegistry 创建并持有当前实例；负责页面资源、组件和响应 Runner |
| `Component` | Page 的 ComponentManager 按 DOM 创建；负责一块 DOM 的交互及释放 |

`Page` 位于 `oldman-web/core`，提供 `root`、`signal`、`http`、`i18n`、`logger`、`components`、`responseActions` 和可选 `feedback`。`BasePage` 位于 `oldman-web/app`，增加声明式 loader、动态组件内容、初始 loading 与主 Frame 请求状态处理。`DashboardPage` 位于 `oldman-web/dashboard`，再安装 Sidebar、Topbar、默认 Feedback、返回顶部和相应共享样式行为。业务页面的卸载、入口加载和新 Page 挂载由 `startOldman()` 安装的统一 Page 生命周期协调，不由旧 BasePage 承接新页面的私有组件。

Dashboard 本身就是 Page。壳上的 Feedback 设置为 Page 的默认 feedback，普通子页面直接复用，不需要另一套全局反馈路径。业务自定义 Page 应继承 DashboardPage；从底层 Page 开始时不能假定已经有壳、loader 或 Feedback。

## 生命周期和释放

Page 钩子为 `beforeMount()`、`mount()`、`afterMount()`、`beforeUnmount()`、`unmount()`。覆盖 BasePage/DashboardPage 的已有钩子时调用 super，否则会跳过组件或壳初始化。

`this.on()`、`this.onCustom()` 用于委托事件；`this.listen()` 用于明确对象；`this.timers` 管理定时器；`this.cleanup(callback)` 登记自建资源的清理。Page 销毁会取消 signal 并运行已登记清理。DOM 之外的订阅、原生 timer、第三方实例不能因为节点被移除就自动消失。

私有动作使用 Demo 的实际 `example_mark`，不是另外构造一个未接线的动作。下面是 ExamplesPage 类内的方法原文；文件已导入 ResponseAction/ResponseActionContext：

```typescript
  override async handleResponseAction(
    action: ResponseAction,
    context: ResponseActionContext
  ): Promise<boolean> {
    if (action.action !== "example_mark") return super.handleResponseAction(action, context);
    if (typeof action.target !== "string" || typeof action.text !== "string") {
      throw new Error("Example mark Action requires a target and text");
    }
    const target = this.root.querySelector<HTMLElement>(action.target);
    if (!target) throw new Error(`Example mark Action target was not found: ${action.target}`);
    target.textContent = action.text;
    return true;
  }
```

对应后端在 [views/modals.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/modals.py) 的 example_action_private 返回 _ExampleMarkAction；可在 `/examples/modals/actions` 页面操作。框架不认识的动作先交给当前 Page，返回 true 表示已处理；不增加另一套全局事件协议。精确规则见[有序动作](responses.md)。

## 组件注册

Dashboard 默认使用 `#oldman-main` 作为业务页面 Frame。自定义容器时，在 Page 构造的顶层选项设置一次 `mainFrameSelector`，例如 `super({ root, mainFrameSelector: "#workspace-main", componentLoaders: createDashboardComponentLoaders() })`，并让 HTML 的 Frame、导航链接及响应使用同一目标。Page 生命周期、Page 内侧栏和通知中心都读取 `page.mainFrameSelector`；`sidebarOptions` 不另设主 Frame。独立使用、没有所属 Page 的 `DashboardSidebar` 仍可使用自身的选项。手写主 Frame 同样需要 `data-om-page` 入口标记；内部用于局部更新的嵌套 Frame 不重建 Page。

同一浏览器文档内切页时，Dashboard 保留用户选择的主题和桌面侧栏宽度；默认值在文档首次初始化时应用。这不等于刷新后保存偏好。移动侧栏遮罩由 SidebarMenu 在组件清理时关闭，不能在每个业务 Page 再写一份清理。

Page 卸载由 PageRegistry 统一推进：普通组件交给 ComponentManager，Page 登记的清理回调最后执行。Dashboard 壳的 SSE、通知和组件分别登记到现有清理栈；一项清理失败会记录错误并继续其他清理。扩展 Page 时，通过 `this.cleanup(...)` 登记资源释放，不把单独调用 `beforeUnmount()` 当作完整销毁，也不重复卸载普通组件。

Demo 的 `templates/pages/examples/tables/dynamic.html` 通过 `table.render_shell(html_id="example-projects-table", data_format=table_format, ...)` 输出 Table 壳；完整调用见[教程](../users/tutorial-dashboard.md#3-一份-table两个渲染格式)。不在业务模板另造与服务端 Table 不一致的最小容器。

组件名必须有 loader。`createDashboardComponentLoaders()` 提供完整框架 loader，并把 modal/feedback 替换为共享 Dashboard 主题适配器。`createDashboardCrudComponentLoaders()` 是轻量边界，只自带 sidebar-menu 和 table；需要 Form/Modal 时必须显式补充，不要误认为它与完整 loader 等价。

普通组件从 `oldman-web/components/<name>` 按需导入；Dashboard Modal/Feedback 从 `oldman-web/dashboard/modal`、`oldman-web/dashboard/feedback` 导入。库负责第三方依赖，不应在业务中再复制 Choices、TanStack 或 Modal 提交流程。

动态插入 HTML 时，旧组件先卸载，再插入新内容，加载所需构造器并挂载。内置 Form、Table、Modal、replace_html 已接入相同的组件管理器；主 Frame 的业务导航则经由 Page 卸载/挂载完成清理。自己处理复杂片段时必须使用相同管理器，不能只用源码断言或 innerHTML 替换假装完成。

页面私有组件只在使用它的 Page 中声明 loader，不必注册到全局。例如完整 EPG Demo 的 `frontend/src/pages/examples.ts` 中，`ExamplesPage` 在构造时提供 `realtime-table`、`example-chart`、`navigation-probe`、`icon-catalog`、`feedback-workflow` 等 loader，并在同一个类内处理 `example_mark` 私有响应动作。它们对应 `frontend/src/components/examples/` 中的组件文件。`frontend/src/main.ts` 的 `pageLoader` 按入口名加载 `./pages/examples.ts`；后端示例页面传 `page_entry="examples"`。从 Dashboard 侧栏进入示例与直接打开示例都会创建这个 Page，不应该把 loader 搬到公共 BasePage 来修补入口没有切换的问题。

## Feedback 交互与真实请求

确认框需要等待用户选择，不能用只负责展示的 `FeedbackAction` 代替。实际消费者是 EPG 的 [FeedbackWorkflow](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/feedback-workflow.ts)，页面为 `/examples/messages/feedback`。它从 `oldman-web/core` 导入 Component，从 `oldman-web/components/feedback` 导入 Feedback；mount 时取得 `this.root` 和 `this.page?.feedback`，分别检查 HTMLFormElement、Feedback。Dashboard 已在普通内容挂载前准备其主题 Feedback；类型检查是为了取得 confirm/prompt，不是创建实例。

原生表单承载 project_id、请求地址和返回 HTML 的目标。其 `data-om-action="post"` 供手动 `runAction` 读取参数，未声明普通 `form` loader，两个操作按钮都是 `type="button"`。组件阻止原生 submit，自己绑定点击监听。不能在此再叠加普通 Form 的自动提交。

以下是该组件内确认分支的原文；feedback 是 mount 已检查的实例，projectName 来自当前选中的 option：

```typescript
          const confirmed = await feedback.confirm({
            title: this.i18n.t("Move this project to review?"),
            text: projectName,
            icon: "question",
            showCancelButton: true,
            confirmButtonText: this.i18n.t("Move to review"),
            cancelButtonText: this.i18n.t("Cancel")
          });
          if (!confirmed) return;
```

输入分支调用 `feedback.prompt<string>`，用 `inputValue` 设置旧名称、`inputLabel` 标注用途、`inputValidator` 校验去空白后的长度。它先判断 `result.isConfirmed`，再取得 `result.value`；不能仅检查 value，因为取消和合法空值不是同一语义。本例业务不接受空名称，服务器也独立执行相同的业务校验。

等待用户结果之后、发请求之前检查 `this.signal.aborted`。随后执行的原文如下；operation 来自按钮，name 来自已确认输入，form 是原生参数表单：

```typescript
        if (this.signal.aborted) return;
        const response = await this.preloader.withLoading(() => this.runAction(form, {
          params: { operation: operation ?? "", name },
          signal: this.signal
        }));
```

`runAction` 使用已有公共 HTTP、CSRF 和 Page Runner；本例没有手写 fetch、复制响应解析或添加内置动作。`withLoading` 只在确认后的请求期间显示局部遮罩。组件从打开对话框到操作结束禁用两个按钮，在 finally 恢复。普通网络/HTTP/业务错误由公共链路显示；组件 catch 只处理对话框等调用异常，取消时直接结束，不能再次弹“请求失败”。监听由 Component 生命周期释放。

后端 [example_feedback_project](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/messages.py) 使用 csrf_protect 和 Demo admin_required，检查 operation、project_id、名称及记录存在性。review 状态重复提交返回非零业务码而不是成功；成功先退出 db_manager.get_session 的事务，再渲染 `_project_result.html`，返回 `data={id,name,status}`、ReplaceHtmlAction、FeedbackAction。模板正常转义名称，slug 不受改名影响。前端收到成功 data 后更新对应 option 的文字，避免再次输入仍显示旧名称。

验证要包含取消无 POST、真实库更新、业务拒绝、403/断网后的恢复、窄屏/键盘以及 Turbo 离开。浏览器暂扣已返回响应、切页后释放时，旧组件请求取消，结果和 toast 不得污染新 Page。服务器可能已提交，重新进入会读到新值；本例不承诺取消数据库事务，不增加导航锁或持久补偿机制。

## Modal 只是容器

Demo 的 [tables/dynamic.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/tables/dynamic.html) 使用共享 `modal` 宏建立 `#example-project-modal`。按钮的 `data-om-modal-target` 指向它，`data-om-modal-url` 指向新建/编辑/删除视图。完整宏、GET 与提交源码见[教程](../users/tutorial-dashboard.md#4-modal-只负责装入内容)，不用另写一套 HTML 骨架。

声明式远程加载使用 Modal parts JSON。通用 parts 有 title/body/footer；Demo 的 Dashboard Modal 实际接收 `{"title": "...", "html": "<form>..." }`，其中 html 装入内容区。它不是 ResponseAction JSON。`loadParts(url)` 处理这种分部内容；需要真实 HTML HTTP 响应时使用 `loadContent(url)`，不要混淆两种方法。

声明式触发先加载内容，成功后才打开 Modal。失败会设置 error 状态并派发 om:modal:error，但不打开尚未加载成功的内容；共享点击入口同时使用所属 Page 的现有 Feedback 显示“请求失败”。Demo 不需要额外监听这个事件再弹一次提示。离开页面或销毁组件导致的请求取消保持静默，不把旧页面的错误带到新页面。

直接调用 `loadParts/loadContent` 时，方法仍将原异常抛给业务调用方，不自动再弹 Feedback；调用方按自己的交互流程处理。没有 Page 的独立底层 Modal 会记录声明式点击的原错误，不偷偷创建全局 Feedback。隐藏容器里的状态文字不是可见错误提示；需要用户反馈的页面应提供 Page/Feedback，一次失败只在负责该请求的入口显示一次。

公开方法包括 `open(trigger?)`、`close(reason?)`、`setContent(content)`、`setParts(parts)`、`loadParts(url)`、`loadContent(url)`、`setStatus(status, message?)`、`destroy()`。远程 load 方法处理旧子组件卸载和新组件挂载；简单 set 方法只设置内容，不等价于完整远程生命周期。

Modal 动态内容中的 Form 仍声明 `data-om-component="form"`。提交响应可以更新 Form、关闭 Modal、刷新 Table 或跳转，全部交给 Form 和 Runner。不另设 Modal 专属的字段校验或保存协议。

`om:component:before-dynamic-content-mount` 允许在同步回调中调用 `detail.waitUntil(promise)` 登记异步 loader。BasePage 已处理正常 loader；只有自定义加载机制才需要监听，不必每个业务 Modal 都写一份。

DashboardModal 提供主题选择器、焦点、动画与遮罩适配。`data-om-keyboard="false"` 禁止 Escape 关闭；`data-om-backdrop="static"` 禁止外部点击关闭。保留 dialog 语义、标题关联、可访问关闭按钮和键盘操作，不为视觉复制另一套 Modal。

## Table 操作

`Table` 从 `oldman-web/components/table` 导入。已挂载实例从 `page.components.get(element)` 取得，并检查实例类型后调用：

- `await table.reload()`：按当前源地址、分页、搜索与筛选重新请求。
- `await table.refresh(url)`：显式请求一个地址。
- `await table.applyFilterForm(form)`：把筛选表单接到同一 Table。

服务端 Form 用 `ReloadTableAction` 更简单，不必在 om:form:success 中再刷新一次。Table 会处理加载状态、过期请求及动态内容挂载。它没有公开的 updateCell API；实时显示可以在 Page 中用稳定行/列 DOM 定位更新，但不要冒充已修改数据库或插件内部数据。

## HTTP、Actions 与页面导航

`page.http` 是绑定页面 signal 的公共 Client。`getJson<T>()`、`postJson<T>()`、`html()` 返回数据；`postForm<T>()` 返回带 status/data 的结果。HTTP 默认超时 30 秒，自动附带 X-Requested-With，写请求读取可用 CSRF 令牌。自己使用 fetch 时不会自动获得这些行为。

通用 `data-om-action` 用于少量 HTML 声明式请求，远程成功响应固定为 actions JSON。URL 从 data-om-url、href 或表单 action 等明确来源取得，更新目标按响应协议处理。不要在同一个 Form 上叠加 Form 提交与 data-om-action 两套提交监听。

`data-om-confirm` 在请求前确认，startOldman 默认使用浏览器原生 confirm，取消不发请求。需要主题确认框时可通过 startOldman 的 actions.confirm 扩展，但 EPG 项目删除示例采用[普通确认 Modal Form](../users/tutorial-dashboard.md#6-成功后按顺序执行界面动作)，不假称该 Demo 已配置另一条确认回调。不要为复制示例额外调用第二次 startOldman。

Turbo 整页访问和 `#oldman-main` 的业务页面导航都会清理旧 Page、创建新 Page。主 Frame 收到响应后，统一生命周期通过 Turbo 的暂停/恢复渲染入口等待旧 Page 的异步清理，然后允许替换 DOM，加载并挂载目标 Page。侧栏和顶栏 DOM 可以保留，但它们所属的旧 Page、组件事件、计时器和 SSE 会正常释放，新 Page 重新建立自己的资源；不是“常驻壳 Page＋业务子 Page”两层实例。

两个 URL 即使都使用 `ExamplesPage`，切页时也创建不同实例。缓存的是已经导入的 JS 模块和 Page 类，不是已经离开的页面实例。需要手写主 Frame 时，响应应包含 `<turbo-frame id="oldman-main" data-turbo-action="advance" data-om-page="examples">…</turbo-frame>`；body 与 Frame 的入口名相同。没有提供新入口名时沿用当前入口，但仍重建实例。优先使用共享宏，不在各页面重复拼这些属性。Frame 导航随后产生的文档级事件不再重复挂载或清理新组件 loading；浏览器前进/后退仍走对应的恢复生命周期。

Form、Table、Modal 和 `ReplaceHtmlAction` 在当前页面更新局部 HTML 不属于业务页面导航，只卸载和挂载受影响的组件。尤其是 Action 自己替换发起请求的 Form 后，同一列表的后续动作仍可继续；不能将它误判为用户离开。用户真正导航、刷新或关闭页面时，旧响应和剩余 UI Actions 则被放弃，不等待执行完、不在新 Page 恢复；取消前端操作不保证服务器撤销已经处理的请求。

在新页面响应到达之前不会提前销毁旧 Page。导航请求失败时，原页面保留并结束 loading、显示现有 Feedback。框架禁用链接预取，不要为局部刷新另加 Prefetch，也不建立必须等待任务完成的全站导航锁。

Page 和 Component 在进入 `unmounting` 时立即取消自身 `signal`，不是等清理回调执行完才取消；Page 取消也会取消所属组件。框架随后依次清理普通组件、外壳及其他已登记资源，完成后才让 Turbo 替换 DOM。挂载还在等待页面类或组件模块时也可以取消；旧模块下载可以继续，但迟到结果不能重新挂载旧页面、卸载新页面或拆掉当前全局运行时。

框架在自己控制的挂载步骤之间检查取消。用户自定义的异步 hook 不会被 JavaScript 强制中断：使用 `this.http` 获得请求取消；自己等待其他异步操作后，在操作 DOM、登记资源或启动订阅之前调用 `this.signal.throwIfAborted()`。卸载 hook 用于释放已有资源，不应通过已经取消的 Page/Component HTTP Client 再启动业务请求。导航造成的取消正常结束旧挂载；当前有效挂载的真正异常仍报告错误并清理已获得的资源。

请求失败时要结束 loading，使用已有 Page Feedback 明确提示；取消旧请求不是用户需要确认的错误。动态更新组件、浏览器后退、离开正在加载的页面和服务器离线都应使用真实浏览器验证，不能只观察接口返回 200。

主 Frame 导航收到 HTML 错误时继续由 Turbo 显示错误页面；收到纯文本或 JSON 的 HTTP 错误时，BasePage 结束遮罩并调用现有 Page 的请求失败提示，保留旧页。这个兜底不执行错误响应中的 actions，也不接管 Form、其他 Frame 或正常响应。
