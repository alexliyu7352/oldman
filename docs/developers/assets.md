# 前端资源、样式、图标和翻译

Python 模板输出 HTML，`oldman-web` 提供浏览器行为和共享样式，应用自己的 Vite 工程把入口编译成可部署资源。本章使用 EPG Demo 的真实路径、构建脚本和 `app:main` bundle。

| 环节 | Demo 源文件 |
| --- | --- |
| 依赖与本地源码关联 | [scripts/bootstrap.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/scripts/bootstrap.py)、[frontend/.pnpmfile.cjs](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/.pnpmfile.cjs) |
| 构建脚本、入口与 Vite | [frontend/package.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/package.json)、[vite.config.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/vite.config.ts)、[src/main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) |
| CSS 与图标输出 | [src/css/app.css](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/css/app.css)、[src/css/generated/icons.css](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/css/generated/icons.css) |
| 服务端资源标签 | [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py)、[templates/base.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/base.html) |
| 浏览器翻译生成 | `oldman i18n compile-frontend`（框架 CLI）、[babel.cfg](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/babel.cfg) |

## 安装与公开导入

Node.js 至少 20。Demo 已在 package.json 中声明 Vite、Tailwind、TypeScript、Sass、字体和需要的插件，不要用一个不完整的 pnpm add 清单覆盖它。在 Demo 根目录按[入门说明](../users/getting-started.md)执行：

```sh
python3 scripts/bootstrap.py
```

该脚本创建 Demo 自己的 Python 环境并安装前端依赖。存在约定的同级框架源码目录（oldman_framwork 或 oldman）时，用 Demo 内的 `.local/oldman` 链接关联它；Python 使用 editable 安装，pnpm hook 在安装时选择本地 oldman-web，但不改写提交到仓库的 package.json 版本声明。没有本地源码时才使用发布包，前提是对应版本在包索引可用。

Demo 的 Vite 配置还将 oldman-web 的公开导入映射到本地源码，因而调试 TypeScript 不必每次先重新编译框架 dist。没有本地源码时则使用包的正式 exports/dist。这个行为来自 Demo 的显式接线，不是所有 Vite 项目自动具备的能力。不要把它改成到处导入框架私有 src，或修改框架的依赖声明来迁就消费者。

公开入口：

| subpath | 用途 |
| --- | --- |
| `oldman-web/core` | Page、Component、运行时、HTTP、i18n、事件、动作类型 |
| `oldman-web/app` | BasePage，通用动态页面生命周期 |
| `oldman-web/dashboard` | DashboardPage 与默认 loaders |
| `oldman-web/dashboard/modal`、`.../feedback` | Dashboard/Admin 共用主题适配器 |
| `oldman-web/components/<name>` | 单个组件按需导入，例如 form、table、select |
| `oldman-web/sse` | 浏览器 SSE 客户端 |
| `oldman-web/styles/tailwind.css`、`.../icons.css` | 共享样式入口 |

不要导入包私有 src/dist 深层文件。底层插件依赖由 oldman-web 声明；只消费共享 Table/Select 的普通应用，不需要为此再声明 TanStack/Choices。Demo 自身也列出了这些依赖，并在本地源码调试时按 Vite 的 localOldmanWebDependencies 做去重；这是当前 Demo 的实际构建配置，不应为了精简文档擅自删掉。应用直接调用插件 API 时仍需声明自己的直接依赖。

Sass 是应用构建工具，不是业务插件。部分组件导入 SCSS，Vite 从应用根解析其编译器。pnpm 的隔离布局或 link 安装下，即使 oldman-web 声明了 Sass 依赖，也不能保证 Vite 从应用找到它；在应用 devDependencies 中显式安装 sass，避免依赖偶然提升。

## CSS 入口

Demo `frontend/src/main.ts` 导入 `@app/css/app.css`；Vite 的 `@app` alias 指向 frontend/src。实际 CSS 文件是 `frontend/src/css/app.css`，以下是它开头的连续节选：

```css
@import "@fontsource/dm-sans/latin-400.css";
@import "@fontsource/dm-sans/latin-500.css";
@import "@fontsource/dm-sans/latin-600.css";
@import "tailwindcss";
@import "oldman-web/styles/tailwind.css";
@import "oldman-web/styles/icons.css";
@import "./generated/icons.css";
```

相对路径按 CSS 文件所在位置解析，不按终端工作目录。该文件的业务扫描项是 `../../../templates`、`../**/*.ts`、`../../../apps/**/*.py`，分别对应项目模板、frontend/src 的 TypeScript 和业务 Python；Python 回调也可能输出 utility class，不能漏掉。

框架共享 CSS 自带从框架 Python/Jinja 生成的 inline 类清单，并扫描包内前端类，因此消费者不需要另找 Python 模板目录。Demo只扫描自己项目的templates、前端TS和apps中的Python类名；框架类由导入的共享清单提供，不依赖源码仓库的相邻目录或机器上的固定路径。

CSS 只改变视觉，不能替代 JS loader；只有 data 属性而没有启动 Page，也不会凭空产生组件行为。反过来，没有样式的运行时也不会自动变成完整 Dashboard。

DM Sans 只作为拉丁字符字体。共享样式针对简繁语言回退到系统中文字体，不默认下载大体积中文字体包。中文环境需系统有可用中文字体；项目需要统一跨设备中文字形时自行选定并安装授权合适的字体，不把英文字体的存在当成中文已覆盖。

## Vite 和服务端 bundle

Demo Vite 配置的 build 对象原样如下，是 defineConfig 内的节选，不是整份可替换配置。rootDir 在文件开头用 import.meta.url 定位 frontend 目录：

```typescript
  build: {
    emptyOutDir: true,
    manifest: true,
    outDir: resolve(rootDir, "../static/dist"),
    rollupOptions: {
      input: {
        main: resolve(rootDir, "src/main.ts")
      },
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/simplebar") || id.includes("node_modules/node-waves")) {
            return "vendor-ui";
          }
          return undefined;
        }
      }
    }
  },
```

完整配置还包含 `base: command === "build" ? staticDistBase : "/"`，staticDistBase 为 `/static/dist/`；plugins 包括 tailwindcss，resolve 包括应用 alias 与本地源码关联。生成 manifest 位于 `static/dist/.vite/manifest.json`。emptyOutDir 只清理这个构建输出目录，不能把它指向整个 static、上传目录或工作区。

生产构建使用 Demo 根目录的 `pnpm --dir frontend build`，会先执行 prebuild 的图标和翻译生成；直接调用 `vite build` 不等同于走完这些准备步骤。

服务端在 `init()` 里注册项目 bundle；四个名字都来自 `oldman.web.staticfiles`，settings 是项目全局配置，同文件定义 `APP_MAIN_BUNDLE = "app:main"`：

```python
registry = app_bundle_registry(app)
register_project_bundle(
    registry,
    name=APP_MAIN_BUNDLE,
    entry_path="src/main.ts",
    static_root=settings.web.static.root,
    static_url=settings.web.static.url,
    dev_mode=dev_mode_requested(),
    dev_server_url=settings.web.frontend.vite_dev_server_url,
    passthrough_prefixes=("theme/",),
)
registry.install_template_globals(app.ext.environment)
```

`app_bundle_registry(app)` 返回该 app 唯一的 registry（内置 Admin 也往同一个里注册）；`register_project_bundle()` 在产品模式读取 `<static_root>/dist/.vite/manifest.json`、从 `<static_url>/dist` 输出资源，缺 `web.static.root`/`web.static.url` 时立即报错，开发模式则全部指向 `dev_server_url`；`dev_mode_requested()` 读取 `OLDMAN_DEV` 开关（`oldman <service> dev` 会设置它）；`install_template_globals()` 把 `bundle_entry`、`bundle_styles` 等七个 `bundle_*` 模板全局注册到 Jinja 环境。`prepare_server()` 再调用 `app_bundle_registry(app).ensure_build_available(APP_MAIN_BUNDLE)` 检查生产入口，缺 manifest/入口会报错，不能把没有脚本的页面当成正常启动。

模板 base.html 对应的整个 block 是：

```jinja
{% block dashboard_head_assets %}
  {{ bundle_client(app_main_bundle) }}
  {% block page_assets %}{% endblock %}
  {{ bundle_modulepreload(app_main_bundle) }}
  {{ bundle_styles(app_main_bundle) }}
  {{ bundle_script(app_main_bundle) }}
{% endblock %}
```

app_main_bundle 就是注册的 `app:main`。方法根据模式读取 manifest 或生成 Vite 地址，不手工猜 hash 文件名。一个 Registry 可以有多个命名 bundle；asset_url 查 manifest（Demo 的 theme/ 是显式直通前缀），asset_base_url 返回资源基址。模板还用它输出 `oldman-asset-base` meta，浏览器据此加载 i18n JSON。

开发模式通过 StaticBundle 的 dev_mode/dev_server_url 使用 Vite；上面的 bundle_client 独立输出开发客户端。通用 entry_tags 也支持 include_dev_client 参数，但 Demo 没有同时调用两套组合标签。

Demo 可以在两个终端分别运行 `pnpm --dir frontend dev` 和 `./run.sh web dev`；或者在项目根执行 `python3 scripts/dev.py`，由这个独立辅助脚本同时启动 Vite 与后端。Web 默认 17997，Vite 5173；不要同时启动两套占用相同端口的服务。run.sh 仍只把参数转发给 Demo 环境的 oldman，既不选择服务，也不暗中启动 Vite。预览模板用的 Nunjucks 与测试数据不是后端 HTTP/数据库/权限验收，完整功能仍访问 Sanic 页面。

`./run.sh web static collect` 收集框架静态资源，不编译应用 TypeScript。Demo 的生产顺序是 build → static collect → web start，完整初始化见入门说明。Admin 内置 bundle 随 Python 包提供；业务 bundle 仍需要自己的 build。Admin Demo 的独立 CSS bundle 和 extension_bundle_name 用法见[Admin 教程](../users/admin.md)，不启动第二套 Admin runtime。

## 图标

当前支持三套 class 名：`ri-*`（Remix Icon）、`mdi-*`（Material Design Icons）、`bx-*`（BoxIcons）。完整图标目录分别见 [Remix Icon 图集](https://icon-sets.iconify.design/ri/)、[Material Design Icons 图集](https://icon-sets.iconify.design/mdi/)、[BoxIcons 图集](https://icon-sets.iconify.design/bx/)。这些是选型目录，不是当前页面图标库存。

Demo `/examples/ui/icons` 在 [icons.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/icons.html) 中给出完整图标库入口、添加步骤和可复制代码。下方是该页代码展示区的内容，将模板里的 HTML 实体还原为用户看到的代码：

```html
<button type="button" aria-label="Open dashboard">
  <i class="ri-dashboard-2-line" aria-hidden="true"></i>
</button>
```

AppConfig.icon 也使用这种 class。图标按钮仍须提供 aria-label 或可见文字，不把图标名称当操作说明。

在 Demo 根目录运行已有脚本，不另写一套扫描范围：

```sh
pnpm --dir frontend generate:icons
```

frontend/package.json 的 scripts 中以下配置是原值节选，其他脚本仍保留：

```json
{
  "generate:icons": "oldman-web-icons --output src/css/generated/icons.css --source src/components --source src/pages --source src/main.ts --source ../templates --source ../apps --exclude-shared",
  "generate:i18n": "../run.sh i18n compile-frontend --service web",
  "prebuild": "pnpm generate:icons && pnpm generate:i18n",
  "predev": "pnpm generate:icons && pnpm generate:i18n",
  "pretypecheck": "pnpm generate:icons"
}
```

共享 icons.css 只带框架自身图标，生成的 src/css/generated/icons.css 带应用实际使用的图标，两者都由 app.css 引入。扫描 TypeScript、模板和 Python，所以 AppConfig/菜单中的图标也能进入构建。动态图标名应在扫描来源中保留完整字符串，不能指望字符串拼接被推理出来。Demo 的图标页展示的是样本，不是所有已支持图标的目录。

Demo 已将生成命令接入上述生命周期，并提交生成结果。生成器会排除测试和 vendor/theme/public/static/dist 等目录；不应把整套模板图标库复制进项目。生成器依赖已经随 npm 包声明。

## 共享视觉变量

使用当前共享语义变量，不在每页另写一套 card/按钮颜色。默认值来自 Tailwind 4 调色板，不是没有定义的“green”或“gray”：

| 语义 | 当前默认 |
| --- | --- |
| primary / hover / active / soft | slate-900 / slate-800 / slate-700 / slate-100（单色主色；暗色下 slate-50 / 200 / 300 / 800） |
| link / focus | blue-600 / slate-500 50% 环 + slate-500 边（全站一套焦点环） |
| success / info / warning / danger | emerald-600 / sky-600 / amber-600 / rose-600；各有 `-soft`、`-text`、`-border` |
| 背景 / surface / 边框 | slate-50 / white / `--om-color-border` 8% 黑（`-soft` 5%、`-strong` 16%） |
| 正文 / 次要文字 | slate-600 / slate-500，标题 slate-900 |
| 签名渐变 | `--om-signature`：blue-600 → green-600，只用于品牌标、切页进度条、图表主序列面积 |
| 控件高 | `--om-control-height-xs/-sm//-lg`：1.5 / 2 / 2.25 / 2.5rem；内边距 `--om-control-padding-sm//-lg`：0.75 / 1 / 1.5rem |
| 控件 / 菜单项 / 卡片与浮层圆角 | 0.5rem / 0.375rem / 0.75rem |
| 字号 | `--om-font-size-page-title` 1.375rem、`-group-title` 1.125rem、`-section-title` 1rem、`-body` / `-control` / `-label` 0.875rem、`-meta` 0.75rem |
| 页面间隙 / 卡片内距 / 表格行高 | `--om-page-gap` 1.5rem / `--om-surface-padding` 1.25rem / `--om-table-row-height` 2.75rem（紧凑 2.25rem） |
| 阴影 | 卡片无阴影（borders-only）；`--om-shadow-dropdown`、`--om-shadow-modal` 只给浮层 |
| 动效 | `--om-motion-fast/normal/slow/page` 120 / 150 / 200 / 320ms；`--om-ease-standard`（进入）、`-move`（位移）、`-exit`（退出） |
| 图表 | `--om-chart-1…6` 是字面量十六进制（blue / emerald / sky / amber / rose / violet 500，暗色 400），因为 ApexCharts 要用它们计算渐变与图例色块；`--om-chart-grid`、`--om-chart-axis-text` 仍是变量引用 |

共享 ApexChart 在没有显式写的情况下应用"控制台"图表主题：不显示工具栏、字体继承页面、只保留虚线横向网格、坐标轴无轴线与刻度、序列色取自 `--om-chart-1…6`、面积图填充 22% → 0 渐变、不印数据点标签。业务 options 里写了同名项就以业务为准。

组合类按"壳层 → 表面 → 浮层 → 状态"分层：壳层是 `oldman-sidebar`、`oldman-topbar`、`oldman-breadcrumb`、`om-page-header`、`om-page-progress`；表面是 `om-button`、`om-field`、`om-check`、`om-badge`、`om-card`（`om-table-card`、`om-form-card`、`om-stat-card`）、`om-table`、`om-filter-toolbar`、`om-tabs`、`om-segmented`；浮层是 `om-dropdown-menu`、`om-tooltip-content`、`om-modal`（`om-modal-dialog-sm`、`om-confirm-*`）、`om-toast`、`om-alert`；状态是 `om-empty`、`om-skeleton`、`om-table-empty-cell`。用法语法见 [用户文档的组件页](../users/components.md)。

变量定义在共享 CSS；例如 `--om-color-primary`、`--om-color-border`、`--om-shadow-card`。应用主题可以集中覆盖这些变量，再在组件中消费。不要只改某个页面的边框或成功颜色而称作更新主题。暗色使用框架的 data-theme 约定。

## 翻译不是第二套前端 domain

项目 Python、Jinja、App CLI 和前端源词合并到 `messages.po`。后端运行时用 MO，浏览器用 JSON；它们是同一份翻译的不同产物，不单独维护一套 frontend/js domain。

Demo 根目录 babel.cfg 的实际 Jinja 段如下：

```ini
[jinja2: templates/**.html]
encoding = utf-8
extensions=jinja2.ext.i18n,oldman.web.template.I18nExtension,oldman.web.security.csrf.CsrfExtension
silent=False
```

保留同文件中 apps、config、core、services 的 Python 扫描规则，以及 .venv/node_modules/scripts/tests 的排除项；这里只展示 Jinja 段，不是用它覆盖整个 babel.cfg。运行 extract 遇到扩展导入错误时先修正应用配置，不关闭 CSRF 或让解析器静默忽略模板。

Demo 已有简繁 PO，更新时在项目根运行以下命令：

```sh
./run.sh i18n extract
./run.sh i18n update
# 编辑 locales/<locale>/LC_MESSAGES/messages.po 后：
./run.sh i18n compile
pnpm --dir frontend generate:i18n
```

新增语言才执行 `i18n init <语言代码>`；命令使用标准代码 zh-Hans、zh-Hant，落盘的 Babel 目录为 zh_Hans、zh_Hant，不要把目录名直接当 CLI 参数。已有目录不要重复 init。

`generate:i18n` 执行框架 CLI `oldman i18n compile-frontend --service <服务名>`，它是浏览器语言包的唯一入口（项目不再自带一份编译脚本）。命令按服务约定读取四个位置：`data/<服务名>_settings.yaml`、`locales/`、`frontend/public/i18n/`、`frontend/src/i18n/generated.ts`：

1. 用框架 I18nConfig/LanguageRegistry 解析配置的语言、别名和默认语言；配置文件不存在、语言为空或默认语言不在集合中时直接报错。
2. 逐语言读取 `locales/<babel_locale>/LC_MESSAGES/messages.po`，编译成浏览器词典。
3. 浏览器词典写入 `frontend/public/i18n/<语言代码小写>.json`，例如 zh-hans.json；语言清单写入 `frontend/src/i18n/generated.ts`，包含 catalogPath、别名、旗帜 URL 等。
4. 先在临时目录生成并校验完整集合，再发布词典目录，最后替换清单；正常失败路径保留匹配的旧产物。清单必须落在词典目录之外，否则发布那一步会连它一起换掉——这种接线会在开始构建前就报错。
5. prebuild/predev 执行该命令，Vite 再把 public/i18n 发布到静态输出或开发服务器。

语言清单是前端 import 的 TypeScript 模块，所以语言集合随 bundle 一起到达，启动不需要再取一次清单；代价是**新增语言后必须重新构建前端**，只跑 i18n 编译不够。需要不同路径的项目直接调用 `oldman.web.i18n.frontend_build.build_frontend_i18n()` 并显式给出四个位置。

PO 不存在时会生成对应语言的空 messages 字典；这不等于该语言翻译完整。不要用“JSON 文件存在”代替翻译检查。

### 三份语言列表

同一个“有哪些语言”在运行时有三个来源，只有第一个会在改完配置重启后立刻变化：

| 列表 | 来源 | 什么时候更新 |
| --- | --- | --- |
| 切换器菜单（用户点的那个） | `settings.i18n.languages`（`language_menu_items()`） | 改配置 + 重启 |
| 后端文案 | `locales/` 编译出的 `.mo` | `i18n compile` |
| 浏览器文案与前端清单 | `frontend/public/i18n/` 与 `generated.ts` | `i18n compile-frontend` + 重新构建前端 |

只改配置就会出现“菜单里有、点下去是 msgid”的语言。`ensure_frontend_catalogs(registry, bundle_name, source_dir=...)` 把它变成启动期的硬失败：配置里的每种语言都必须在收集后的静态根里有一份词典，脚手架的 `prepare_server` 已经接好；开发模式改为对源目录告警，因为那时词典由 Vite 直接提供。

框架自带的 Admin 不走这条链路：它的语言包是挂在自己前缀下的一条路由，内容在请求时按 locales 根合并（项目可以覆盖框架文案），前缀又是安装时才定的，两者都没法预生成成构建产物。扩展 Admin 的项目补翻译加一个 locales 根即可，不需要前端 i18n 构建。

提取时有三个明确来源：项目根按 babel.cfg 扫描当前项目的 Python/Jinja；安装的 oldman 按包内 framework-babel.cfg 扫描框架 Python/Jinja（包括 CLI）；项目 frontend/src 的 TypeScript AST 和框架自带前端词清单再并入同一个 POT。App 的 commands.py 只要位于项目 Babel 规则覆盖范围，其 lazy help 与其他 Python 文本同样提取。它不是遍历所有已安装第三方包的提取器：第三方 App 应自行发布翻译目录，运行时再按配置接入其翻译来源。

编译时用框架自带前端消息清单和项目 frontend/src 的 AST 提取结果过滤目录，避免把全部后端词发给浏览器。清单只是编译输入，不是额外翻译源，也不需要用户手工维护。TypeScript 提取使用 `i18n.t/tc/tn/tnc` 的静态字面量；动态拼接消息 ID 应改写为稳定字面量，而不是漏掉后继续声称提取完整。

npm 包的底层工具为 `oldman-web-i18n extract --project-root . --source-root frontend/src` 和 `oldman-web-i18n compile-po --fallback-locale en`（从标准输入读取 PO）。普通项目优先使用 Oldman CLI 和脚手架脚本，不另写 PO 解析器。

Demo main.ts 从 `./i18n/generated` 导入 defaultLanguage、languageAliases 和 languageDefinitions；从页面的 oldman-asset-base meta 取得资源基址。它创建 createI18n，交给 createOldmanContext，等待 i18n.init 后才 startOldman，完整代码见[前端入口](frontend.md#demo-的-dashboard-页面入口)。

词典加载不用自己写，`createFetchCatalogLoader` 来自 oldman-web/core：

```typescript
const assetBaseUrl = readAssetBaseUrl();
const i18n = createI18n({
  aliases: languageAliases,
  catalogLoader: createFetchCatalogLoader({ assetBaseUrl }),
  defaultLanguage,
  document,
  http,
  languages: languageDefinitions
});
```

它按 URL 规则解析 `catalogPath`，不改写路径：项目的词典和 bundle 放在一起，写相对路径（`i18n/en.json`），相对 assetBaseUrl 解析；Admin 的词典是另一个挂载点上的路由，写站点绝对路径（`/admin/i18n/en.json`）。剥掉前导斜杠会让后者变成相对当前页面，于是每个非根页面都请求到 404。

生产基址为 /static/dist/，开发模式为 Vite URL，不能把 JSON 路径固定成另一个端口。加载失败（HTTP 错误、网络异常、非法 JSON）都回退空词典，让缺翻译退回 msgid 而不是整页起不来；不能把 fallback 当成加载成功。验证时在 Network 确认实际词典请求、正文翻译和语言切换，不只看下拉菜单是否有简繁选项。

## Dashboard 脚手架的范围

脚手架提供 Web 服务、基础模板、Vite、图标/i18n 工具及错误页；新业务 App 的 views、models、模板和 page.ts 仍要显式创建并加入服务 apps。默认根路径不一定有业务路由；加入 auth/admin App 配置也不等于自动安装 `/admin`。

新建项目时选择 dashboard，按生成 README 操作。已有 API 项目增加前端时可按本章与连续教程加最小入口，不需要重新创建项目、改变数据库身份或复制完整 Demo。
