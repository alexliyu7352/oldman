# oldman-web

Oldman 的 TypeScript 浏览器包：共享 Page 生命周期、Dashboard 壳、Form、Table、Modal、响应动作、SSE 客户端和默认样式。使用原生 DOM，不要求 React/Vue。它不包含业务数据、后端路由或业务页面。

Python 包 oldman 负责服务端模型、表单、Table、模板及权限；两端通过同一 HTML/JSON 协议协作。Admin 和业务 Dashboard 共用本包，不需要两套组件。

## 安装

Node.js 20 或更高。在应用的 frontend 目录：

```sh
pnpm add oldman-web @fontsource/dm-sans
pnpm add -D vite@^5 tailwindcss@^4 @tailwindcss/vite typescript @types/node sass
```

Tailwind 4 用于共享主题；不导入共享 CSS 的应用可不安装它。Sass 是 Vite 编译组件 SCSS 所需的应用构建工具：pnpm 隔离依赖或 link 安装时，不应依赖间接依赖恰好可解析。TanStack、Choices、Swiper 等组件插件则由 oldman-web 声明，不需要消费者重复安装；业务直接调用插件 API 时才自行声明直接依赖。

使用与 Python 框架匹配的版本。本地源码关联需要目标包已有有效 dist，不能只关联没有构建产物的 src。安装成功也不等于已创建后台路由。

## 最小 Dashboard 入口

下面是单页的最小 **API 接线参考**，不是完整 Demo 的源码节选。包含语言目录和按需 Page loader 的实际应用入口见 [EPG main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts)及[浏览器生命周期参考](https://github.com/alexliyu7352/oldman/blob/master/docs/developers/frontend.md)。此处文件为应用 frontend/src/main.ts：

```typescript
import "./app.css";
import { setupPage, startOldman } from "oldman-web/core";
import { DashboardPage, createDashboardComponentLoaders } from "oldman-web/dashboard";

class TasksPage extends DashboardPage {
  constructor(root: HTMLElement) {
    super({ root, componentLoaders: createDashboardComponentLoaders() });
  }
}

setupPage("tasks", TasksPage);
void startOldman().catch((error: unknown) => console.error(error));
```

HTML 使用 body data-om-page="tasks"，并加载该入口构建出的脚本及样式。setupPage 注册类，运行时持有当前实例；每个文档只调用一次 startOldman，不在每个片段或 Modal 中重新启动。

createDashboardComponentLoaders 提供完整默认 loader，并使用 Dashboard Modal/Feedback 主题适配器；createDashboardCrudComponentLoaders 是更小的子集，只预置 Sidebar/Table。需要 Form、Modal 等时不要误用只有两个 loader 的入口。

最小入口没有加载项目翻译 JSON；完整语言切换使用 createI18n、createOldmanContext 和 catalogLoader，Dashboard 项目脚手架已提供接线。

## 样式和字体

目录采用 frontend/src/app.css、项目根 templates/ 和 apps/：

```css
@import "@fontsource/dm-sans/latin-300.css";
@import "@fontsource/dm-sans/latin-400.css";
@import "@fontsource/dm-sans/latin-500.css";
@import "@fontsource/dm-sans/latin-600.css";
@import "@fontsource/dm-sans/latin-700.css";
@import "tailwindcss";
@import "oldman-web/styles/tailwind.css";
@import "oldman-web/styles/icons.css";
@import "./generated/icons.css";

@source "../../templates";
@source "../../apps/**/*.py";
@source "./**/*.ts";
```

相对路径以 CSS 文件位置为准。包内共享样式已带入框架自身的类；应用仍需扫描会输出 class 的模板、Python 和 TypeScript。样式提供 om-card、om-button、om-modal 等语义类和统一视觉变量，不会替代 JS loader。

DM Sans 覆盖拉丁字符，简繁中文回退到系统中文字体。不默认下载大型中文字体；应用需要统一中文字形时自行选择合适字体。颜色、边框和间距应集中覆盖共享变量，不逐页重新定义风格。

## 图标

支持 ri-*、mdi-*、bx-*。共享 icons.css 只包含框架自身图标，应用按实际使用生成：

```sh
pnpm exec oldman-web-icons --output src/generated/icons.css \
  --source src --source ../templates --source ../apps --exclude-shared
```

把命令加入应用 prebuild/predev/pretypecheck。生成器随包提供图标数据，扫描完整 class 字符串，排除测试、vendor、theme、public、static、dist 等目录；不能从动态字符串拼接推断全部图标。提交生成文件可让刚检出的项目具备 CSS 导入目标。

完整图库：[Remix Icon](https://icon-sets.iconify.design/ri/)、[Material Design Icons](https://icon-sets.iconify.design/mdi/)、[BoxIcons](https://icon-sets.iconify.design/bx/)。例如 ri-add-line；装饰图标使用 aria-hidden，纯图标按钮仍须 aria-label。

## 公开入口与动态内容

| 导入 | 作用 |
| --- | --- |
| oldman-web/core | Page、Component、运行时、HTTP、i18n、动作与类型 |
| oldman-web/app | BasePage 和动态页面生命周期 |
| oldman-web/dashboard | DashboardPage、壳和 loaders |
| oldman-web/dashboard/modal、oldman-web/dashboard/feedback | Dashboard/Admin 共用主题适配 |
| oldman-web/components/form、table、select 等 | 单个组件及其公开类型 |
| oldman-web/sse | 浏览器 SSE 客户端 |

不要导入私有 src/dist 深层文件。组件由 Page 管理；动态 HTML 先卸载旧组件，再加载并挂载新组件，离开页面释放请求、监听和插件实例。

Modal 只是容器，内部表单仍由普通 Form 提交。远程 loadParts 消费 title/body/footer JSON，loadContent 消费 HTML；表单保存的 actions JSON 则由 Form 和当前 Page 的 Runner 消费，不能混为同一协议。直接 setContent/setParts 不代替完整动态加载生命周期。

声明式远程内容在成功加载后才打开 Modal。加载失败由共享点击入口使用所属 Page 的 Feedback 提示，并保留 error 状态和 om:modal:error 事件，不需要应用再监听一次弹窗；离页/销毁取消不提示。直接调用 loadParts/loadContent 仍向调用方抛出原异常，由调用方处理。无 Page 的独立底层 Modal 只记录声明式失败，不创建全局 Feedback；隐藏容器的状态本身不可见。完整入口及事件类型见下方 Page 参考。

JSON Table 使用共享服务端 columns/rows/pagination/sort 协议；HTML Table 消费服务端片段。两者均通过 reload 刷新，不能把它们当成任意第三方表格协议。

DashboardPage 已提供默认 Feedback。toast 使用 Toastify，弹窗使用 SweetAlert2，统一通过 Feedback API；显示 toast 不会自动产生持久通知记录。

## 翻译

项目 Python、Jinja、CLI 与浏览器共用 messages PO，浏览器只接收需要的词条 JSON：

```sh
# 在项目根提取 TypeScript；输出供上层工具合并。
frontend/node_modules/.bin/oldman-web-i18n extract --project-root . --source-root frontend/src
# 从标准输入读取 PO，向标准输出写 catalog JSON。
frontend/node_modules/.bin/oldman-web-i18n compile-po --fallback-locale en < locales/en/LC_MESSAGES/messages.po
```

extract 使用 TypeScript AST 识别 i18n.t/tc/tn/tnc，接受字符串字面量或无插值模板字面量。动态消息、缺参数和语法错误以具体文件位置报错。compile-po 保留 context、plural forms 和 pluralRule；项目不应另写 PO 解析器。

Python CLI 负责项目统一 POT/PO/MO，Dashboard 脚手架构建脚本按框架及项目的前端词清单过滤 JSON，再由 Vite 发布。上述底层 compile-po 本身不会自动知道哪些词属于前端。

## 完整文档

[Dashboard 连续教程](https://github.com/alexliyu7352/oldman/blob/master/docs/users/tutorial-dashboard.md) · [组件用法](https://github.com/alexliyu7352/oldman/blob/master/docs/users/components.md) · [Page 和生命周期](https://github.com/alexliyu7352/oldman/blob/master/docs/developers/frontend.md) · [响应协议](https://github.com/alexliyu7352/oldman/blob/master/docs/developers/responses.md) · [构建、图标和翻译](https://github.com/alexliyu7352/oldman/blob/master/docs/developers/assets.md)

发布内容包括 dist、图标与翻译 CLI、类型声明、README 和 LICENSE。应用需要构建自己的入口；后端内置 Admin 资源不替代业务前端构建。
