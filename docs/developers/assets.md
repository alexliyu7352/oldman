# 前端资源、样式、图标和翻译

Python 模板输出 HTML，`oldman-web` 提供浏览器行为和共享样式，应用自己的 Vite 工程把入口编译成可部署资源。本章使用 EPG Demo 的真实路径、构建脚本和 `app:main` bundle。

| 环节 | Demo 源文件 |
| --- | --- |
| 依赖与本地源码关联 | [scripts/bootstrap.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/scripts/bootstrap.py)、[frontend/.pnpmfile.cjs](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/.pnpmfile.cjs) |
| 构建脚本、入口与 Vite | [frontend/package.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/package.json)、[vite.config.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/vite.config.ts)、[src/main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) |
| CSS 与图标输出 | [src/css/app.css](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/css/app.css)、[src/css/generated/icons.css](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/css/generated/icons.css) |
| 服务端资源标签 | [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py)、[templates/base.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/base.html) |
| 浏览器翻译生成 | [scripts/compile_js_messages.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/scripts/compile_js_messages.py)、[babel.cfg](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/babel.cfg) |

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
@import "@fontsource/dm-sans/latin-300.css";
@import "@fontsource/dm-sans/latin-400.css";
@import "@fontsource/dm-sans/latin-500.css";
@import "@fontsource/dm-sans/latin-600.css";
@import "@fontsource/dm-sans/latin-700.css";
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

服务端使用 services/web.py 的完整工厂函数。StaticBundle、StaticBundleRegistry 来自 oldman.web.staticfiles，Path 来自 pathlib，settings 是项目全局配置；同文件定义 `APP_MAIN_BUNDLE = "app:main"`，is_vite_dev_mode() 读取 Demo 的 OLDMAN_DEV 开关：

```python
def create_static_bundle_registry() -> StaticBundleRegistry:
    """创建当前项目的静态资源 bundle registry。"""
    dev_mode = is_vite_dev_mode()
    static_root = str(settings.web.static.root).strip()
    static_url = str(settings.web.static.url).strip()
    if not dev_mode and (not static_root or not static_url):
        raise RuntimeError(
            "Dashboard production assets require settings.web.static.root and "
            "settings.web.static.url; configure them and run "
            "`oldman web static collect` before startup"
        )

    manifest_root = Path(static_root) if static_root else Path()
    registry = StaticBundleRegistry()
    registry.register(
        StaticBundle(
            name=APP_MAIN_BUNDLE,
            entry_path="src/main.ts",
            manifest_path=manifest_root / "dist" / ".vite" / "manifest.json",
            static_url=f"{static_url.rstrip('/')}/dist" if static_url else "",
            dev_server_url=settings.web.frontend.vite_dev_server_url,
            dev_mode=dev_mode,
            passthrough_prefixes=("theme/",),
        )
    )
    return registry
```

WebService.init() 在父类创建 Sanic 后调用 install_template_helpers()；该函数将 bundle_registry 的标签方法注册到 Jinja globals。prepare_server() 再调用 ensure_vite_build_available() 检查生产入口，缺 manifest/入口会报错，不能把没有脚本的页面当成正常启动。

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

Demo 可以在两个终端分别运行 `pnpm --dir frontend dev` 和 `./run.sh web dev`；或者在项目根执行 `python3 scripts/dev.py`，由这个独立辅助脚本同时启动 Vite 与后端。Web 默认 17998，Vite 5173；不要同时启动两套占用相同端口的服务。run.sh 仍只把参数转发给 Demo 环境的 oldman，既不选择服务，也不暗中启动 Vite。预览模板用的 Nunjucks 与测试数据不是后端 HTTP/数据库/权限验收，完整功能仍访问 Sanic 页面。

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
  "generate:i18n": "../.venv/bin/python ../scripts/compile_js_messages.py",
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
| primary / hover / soft | blue-600 / blue-700 / blue-50 |
| success | green-600；soft 为 green-50 |
| info / warning / danger | sky-600 / amber-500 / red-600 |
| 背景 / surface / 边框 | zinc-50 / white / zinc-200 |
| 正文 / 次要文字 | zinc-700 / zinc-500 |
| 普通控件高 | `--om-control-height: 2.375rem` |
| 控件 / 卡片 / 浮层圆角 | 0.375rem / 0.5rem / 0.625rem |
| 页面间隙 / 卡片内距 | `--om-page-gap` / `--om-surface-padding`，均 1.25rem |

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

Demo 的 generate:i18n 执行 `scripts/compile_js_messages.py`。该脚本默认读取 `data/web_settings.yaml` 的 i18n 和 web.static：

1. 用框架 I18nConfig/LanguageRegistry 解析配置的语言、别名和默认语言；配置文件不存在、语言为空或默认语言不在集合中时直接报错。
2. 逐语言读取 `locales/<babel_locale>/LC_MESSAGES/messages.po`，调用 `compile_project_frontend_catalog()`。
3. 浏览器词典写入 `frontend/public/i18n/<语言代码小写>.json`，例如 zh-hans.json；语言索引写入 `frontend/src/i18n/generated.ts`，包含 catalogPath、别名、旗帜 URL 等。
4. 先在临时目录生成并校验完整集合，再发布词典目录，最后替换索引；正常失败路径保留匹配的旧产物。
5. prebuild/predev 执行该脚本，Vite 再把 public/i18n 发布到静态输出或开发服务器。

PO 不存在时，该 Demo 脚本会生成对应语言的空 messages 字典；这不等于该语言翻译完整。不要用“JSON 文件存在”代替翻译检查。其他 Dashboard 项目若采用不同生成脚本，应按自己的实际输出路径接入，不能把 Demo 的文件名当成框架固定命令。

提取时有三个明确来源：项目根按 babel.cfg 扫描当前项目的 Python/Jinja；安装的 oldman 按包内 framework-babel.cfg 扫描框架 Python/Jinja（包括 CLI）；项目 frontend/src 的 TypeScript AST 和框架自带前端词清单再并入同一个 POT。App 的 commands.py 只要位于项目 Babel 规则覆盖范围，其 lazy help 与其他 Python 文本同样提取。它不是遍历所有已安装第三方包的提取器：第三方 App 应自行发布翻译目录，运行时再按配置接入其翻译来源。

编译时用框架自带前端消息清单和项目 frontend/src 的 AST 提取结果过滤目录，避免把全部后端词发给浏览器。清单只是编译输入，不是额外翻译源，也不需要用户手工维护。TypeScript 提取使用 `i18n.t/tc/tn/tnc` 的静态字面量；动态拼接消息 ID 应改写为稳定字面量，而不是漏掉后继续声称提取完整。

npm 包的底层工具为 `oldman-web-i18n extract --project-root . --source-root frontend/src` 和 `oldman-web-i18n compile-po --fallback-locale en`（从标准输入读取 PO）。普通项目优先使用 Oldman CLI 和脚手架脚本，不另写 PO 解析器。

Demo main.ts 从 `./i18n/generated` 导入 defaultLanguage、languageAliases 和 languageDefinitions；从页面的 oldman-asset-base meta 取得资源基址。它创建 createI18n，交给 createOldmanContext，等待 i18n.init 后才 startOldman，完整代码见[前端入口](frontend.md#demo-的-dashboard-页面入口)。

该文件加载单语言词典的完整函数如下；LanguageDefinition 来自 oldman-web/core，assetBaseUrl 由同文件 readAssetBaseUrl() 提供：

```typescript
async function loadLanguageCatalog(language: LanguageDefinition, assetBaseUrl: string) {
  const url = new URL(language.catalogPath.replace(/^\/+/, ""), assetBaseUrl).toString();
  const response = await fetch(url, {
    headers: {
      Accept: "application/json"
    }
  });
  if (!response.ok) {
    return {
      locale: language.locale,
      messages: {}
    };
  }
  return response.json();
}
```

生产基址为 /static/dist/，开发模式为 Vite URL，不能把 JSON 路径固定成另一个端口。这里非成功 HTTP 响应回退空词典，网络异常或非法 JSON 仍可能抛错；不能把 fallback 当成加载成功。验证时在 Network 确认实际词典请求、正文翻译和语言切换，不只看下拉菜单是否有简繁选项。

## Dashboard 脚手架的范围

脚手架提供 Web 服务、基础模板、Vite、图标/i18n 工具及错误页；新业务 App 的 views、models、模板和 page.ts 仍要显式创建并加入服务 apps。默认根路径不一定有业务路由；加入 auth/admin App 配置也不等于自动安装 `/admin`。

新建项目时选择 dashboard，按生成 README 操作。已有 API 项目增加前端时可按本章与连续教程加最小入口，不需要重新创建项目、改变数据库身份或复制完整 Demo。
