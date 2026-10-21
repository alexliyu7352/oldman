# Frontend assets, styles, icons, and translation

Python templates output HTML, `oldman-web` supplies browser behavior/shared styles, and the application's own Vite project compiles deployable assets. This chapter uses actual EPG demo paths, build scripts, and the `app:main` bundle.

| Stage | Demo source files |
| --- | --- |
| Dependencies and local-source linking | [scripts/bootstrap.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/scripts/bootstrap.py), [frontend/.pnpmfile.cjs](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/.pnpmfile.cjs) |
| Build scripts, entry point, and Vite | [frontend/package.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/package.json), [vite.config.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/vite.config.ts), [src/main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) |
| CSS and icon output | [src/css/app.css](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/css/app.css), [src/css/generated/icons.css](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/css/generated/icons.css) |
| Server-side asset tags | [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py), [templates/base.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/base.html) |
| Browser translation generation | `oldman i18n compile-frontend` (framework CLI), [babel.cfg](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/babel.cfg) |

## Installation and public imports

Node.js 20 or later is required. Demo package.json already declares Vite, Tailwind, TypeScript, Sass, fonts, and required plugins. Do not replace it with an incomplete pnpm add list. At the demo root, follow [Run the EPG dashboard demo](../users/getting-started.md) and run:

```sh
python3 scripts/bootstrap.py
```

This script creates the demo's own Python environment and installs frontend dependencies. If a sibling framework source directory (oldman_framwork or oldman) exists, the demo links it through `.local/oldman`. Python uses an editable installation, and a pnpm install hook selects local oldman-web without rewriting committed package.json versions. Without local source, it uses release packages, provided the versions exist in their registries.

Demo Vite configuration also maps public oldman-web imports to local source, so TypeScript debugging does not require rebuilding framework dist each time. Without local source, it uses official exports/dist. This is explicit demo wiring, not automatic behavior in all Vite projects. Do not replace it with private framework src imports throughout the project or modify framework dependencies to accommodate consumers.

Public entry points:

| Subpath | Purpose |
| --- | --- |
| `oldman-web/core` | Page, Component, runtime, HTTP, i18n, events, action types |
| `oldman-web/app` | BasePage and general dynamic-page lifecycle |
| `oldman-web/dashboard` | DashboardPage and default loaders |
| `oldman-web/dashboard/modal`, `.../feedback` | Shared dashboard/Admin theme adapters |
| `oldman-web/components/<name>` | Individual component imports, such as form, table, select |
| `oldman-web/sse` | Browser SSE client |
| `oldman-web/styles/tailwind.css`, `.../icons.css` | Shared style entry points |

Do not import private deep src/dist files. oldman-web declares underlying plugin dependencies; ordinary consumers of shared Table/Select need no additional TanStack/Choices declarations. The demo itself also lists these dependencies and deduplicates local-source development through Vite localOldmanWebDependencies. That is its actual build configuration and must not be deleted merely to simplify documentation. Applications calling plugin APIs directly still declare their own direct dependencies.

Sass is an application build tool, not a business plugin. Some components import SCSS, and Vite resolves its compiler from the application root. With pnpm isolation or linked installations, oldman-web's Sass dependency does not guarantee Vite can find it from the app. Explicitly install sass in application devDependencies rather than relying on incidental hoisting.

## CSS entry point

Demo `frontend/src/main.ts` imports `@app/css/app.css`; Vite's `@app` alias points to frontend/src. The actual file is `frontend/src/css/app.css`. Its opening continuous excerpt follows:

```css
@import "@fontsource/dm-sans/latin-400.css";
@import "@fontsource/dm-sans/latin-500.css";
@import "@fontsource/dm-sans/latin-600.css";
@import "tailwindcss";
@import "oldman-web/styles/tailwind.css";
@import "oldman-web/styles/icons.css";
@import "./generated/icons.css";
```

Relative paths resolve from the CSS file, not the terminal directory. Business scan sources are `../../../templates`, `../**/*.ts`, and `../../../apps/**/*.py`, covering project templates, frontend/src TypeScript, and business Python. Python callbacks can also output utility classes and must be included. The fourth source, `../../../.local/oldman/oldman/web/templates`, is only for framework development, as explained below.

Shared framework CSS includes an inline class list generated from framework Python/Jinja and scans its own frontend classes, so consumers need not locate Python template directories. The demo build relies only on project templates, frontend TS, and apps Python classes; imported shared lists supply framework classes without neighboring source repositories or fixed machine paths. The demo additionally scans framework templates under `.local/oldman` only for live framework development. With sibling source linked, template edits refresh the page and new classes generate immediately. With release packages, the directory is absent and Tailwind skips it.

CSS changes appearance, not JS loaders. Data attributes without a started Page do not create behavior. Conversely, an unstyled runtime does not automatically become a complete dashboard.

DM Sans covers Latin characters only. Shared styles fall back to system fonts for simplified/traditional Chinese rather than downloading large Chinese-font packages by default. Chinese environments need available system Chinese fonts. Projects requiring consistent glyphs across devices should choose/install suitably licensed fonts; a Latin font does not establish Chinese coverage.

## Vite and server-side bundles

The demo's Vite build object follows unchanged. It is an excerpt inside defineConfig, not a complete replacement configuration. rootDir locates frontend through import.meta.url at the start of the file:

```typescript
  build: {
    emptyOutDir: true,
    manifest: true,
    outDir: resolve(rootDir, "../static/dist"),
    // ApexCharts alone is about 580 kB; oldman-web loads it only on pages that have a chart.
    // Any other chunk past 600 kB still gets Vite's warning.
    chunkSizeWarningLimit: 600,
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

The full configuration also includes `base: command === "build" ? staticDistBase : "/"`, with staticDistBase `/static/dist/`, tailwindcss plugins, application aliases, and local-source linking. The manifest is `static/dist/.vite/manifest.json`. emptyOutDir clears only that build directory. Do not point it at all of static, uploads, or the workspace.

Production uses `pnpm --dir frontend build` from the demo root, running prebuild icon/translation generation first. Direct `vite build` does not complete those preparations.

The server registers the project bundle in `init()`. All four names come from `oldman.web.staticfiles`; settings is the project global configuration, and the same file defines `APP_MAIN_BUNDLE = "app:main"`:

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

`app_bundle_registry(app)` returns that app's unique registry, also used by built-in Admin. `register_project_bundle()` reads `<static_root>/dist/.vite/manifest.json` in production and serves URLs under `<static_url>/dist`, failing immediately without `web.static.root`/`web.static.url`. Development URLs all point to `dev_server_url`. `dev_mode_requested()` reads `OLDMAN_DEV`, set by `oldman <service> dev`. `install_template_globals()` registers seven `bundle_*` globals, including `bundle_entry` and `bundle_styles`, in Jinja. `prepare_server()` then calls `app_bundle_registry(app).ensure_build_available(APP_MAIN_BUNDLE)` to check production entries. Missing manifests/entries fail rather than treating a scriptless page as successful startup.

The complete corresponding base.html block is:

```jinja
{% block dashboard_head_assets %}
  {{ bundle_client(app_main_bundle) }}
  {% block page_assets %}{% endblock %}
  {{ bundle_modulepreload(app_main_bundle) }}
  {{ bundle_styles(app_main_bundle) }}
  {{ bundle_script(app_main_bundle) }}
{% endblock %}
```

app_main_bundle is registered `app:main`. Methods read the manifest or produce Vite URLs according to mode rather than guessing hashed filenames. A Registry supports multiple named bundles. asset_url consults the manifest (demo theme/ is an explicit passthrough prefix); asset_base_url returns the asset base URL. Templates also emit it in `oldman-asset-base` meta for browser i18n JSON loading.

Development uses StaticBundle dev_mode/dev_server_url for Vite; bundle_client above emits its development client separately. General entry_tags also supports include_dev_client, but the demo does not call both combined tag approaches.

Run `pnpm --dir frontend dev` and `./run.sh web dev` in separate terminals, or run `python3 scripts/dev.py` at the project root to start Vite/backend together through that standalone helper. Web defaults to 17997 and Vite to 5173; do not start duplicate services on the same ports. run.sh only forwards arguments to the demo environment's oldman. It neither chooses a service nor secretly starts Vite. Use demo example pages, which cover all frontend components, when adjusting styles/components. CSS updates without reload; TypeScript/template edits reload automatically; Python changes require backend restart.

`./run.sh web static collect` collects framework static assets without compiling application TypeScript. Production order is build → static collect → web start; see getting-started instructions for full initialization. Admin's bundle ships with the Python package, while business bundles still require their own build. Collection targets `web.static.root`, defaulting to project `static/`. Existing project files remain; framework/Admin files copy to `static/oldman/`; Apps with `static/` copy names from those directories. The manifest is adjacent at `.static.oldman-static.json`. Copies/manifests are generated and must not be committed. Web/dashboard scaffold `.gitignore` already excludes `static/oldman/` and the manifest; add your own App copies yourself. See [Run and understand the Admin demo](../users/admin.md) for the Admin demo's separate CSS bundle and extension_bundle_name, without a second Admin runtime.

## Icons

Three class families are supported: `ri-*` (Remix Icon), `mdi-*` (Material Design Icons), and `bx-*` (BoxIcons). Full catalogs are [Remix Icon catalog](https://icon-sets.iconify.design/ri/), [Material Design Icons catalog](https://icon-sets.iconify.design/mdi/), and [BoxIcons catalog](https://icon-sets.iconify.design/bx/). These are selection catalogs, not inventories of icons available on the current page.

Demo `/examples/ui/icons` in [icons.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/icons.html) links the complete catalogs, gives addition steps, and provides copyable code. The following reproduces its code-display content, decoding template HTML entities to the code users see:

```html
<button type="button" aria-label="Open dashboard">
  <i class="ri-dashboard-2-line" aria-hidden="true"></i>
</button>
```

AppConfig.icon uses these classes too. Icon buttons still require aria-label or visible text; icon names are not action instructions.

Run the existing script from the demo root instead of writing another scan scope:

```sh
pnpm --dir frontend generate:icons
```

These are unchanged excerpts from frontend/package.json scripts. Retain other scripts:

```json
{
  "generate:icons": "oldman-web-icons --output src/css/generated/icons.css --source src/components --source src/pages --source src/main.ts --source ../templates --source ../apps --exclude-shared",
  "generate:i18n": "../run.sh i18n compile-frontend --service web",
  "prebuild": "pnpm generate:icons && pnpm generate:i18n",
  "predev": "pnpm generate:icons && pnpm generate:i18n",
  "pretypecheck": "pnpm generate:icons"
}
```

Shared icons.css contains framework icons only; generated src/css/generated/icons.css contains icons actually used by the application. app.css imports both. Scanning covers TypeScript, templates, and Python, so AppConfig/menu icons enter the build. Keep complete strings in scan sources for dynamic names; concatenated strings cannot be inferred. The demo icon page shows samples, not every supported icon.

The demo wires generation into the lifecycle above and commits the output. The generator excludes tests and vendor/theme/public/static/dist directories. Do not copy a complete template icon library into the project. Generator dependencies already ship in the npm package.

## Shared visual variables

Use current shared semantic variables rather than separate card/button colors per page. Defaults come from the Tailwind 4 palette, not undefined "green" or "gray":

| Semantic role | Current default |
| --- | --- |
| primary / hover / active / soft | slate-900 / slate-800 / slate-700 / slate-100 (monochrome primary; dark: slate-50 / 200 / 300 / 800) |
| link / focus | blue-600 / slate-500 50% ring + slate-500 border (one shared focus ring) |
| success / info / warning / danger | emerald-600 / sky-600 / amber-600 / rose-600, each with `-soft`, `-text`, `-border` |
| background / surface / border | slate-50 / white / `--om-color-border` 8% black (`-soft` 5%, `-strong` 16%) |
| body / secondary text | slate-600 / slate-500; headings slate-900 |
| Signature gradient | `--om-signature`: blue-600 → green-600, only for branding, navigation progress, and primary chart-series areas |
| Control heights | `--om-control-height-xs/-sm//-lg`: 1.5 / 2 / 2.25 / 2.5rem; padding `--om-control-padding-sm//-lg`: 0.75 / 1 / 1.5rem |
| Control / menu-item / card and overlay radii | 0.5rem / 0.375rem / 0.75rem |
| Font sizes | `--om-font-size-page-title` 1.375rem, `-group-title` 1.125rem, `-section-title` 1rem, `-body` / `-control` / `-label` 0.875rem, `-meta` 0.75rem |
| Page gap / card padding / table-row height | `--om-page-gap` 1.5rem / `--om-surface-padding` 1.25rem / `--om-table-row-height` 2.75rem (compact 2.25rem) |
| Shadows | Cards have no shadow (borders only); `--om-shadow-dropdown` and `--om-shadow-modal` are for overlays only |
| Motion | `--om-motion-fast/normal/slow/page` 120 / 150 / 200 / 320ms; `--om-ease-standard` (entry), `-move` (movement), `-exit` (exit) |
| Charts | `--om-chart-1…6` are literal hex colors (blue / emerald / sky / amber / rose / violet 500; dark 400), needed for ApexCharts gradient/legend calculations; `--om-chart-grid` and `--om-chart-axis-text` remain variable references |

Unless overridden, shared ApexChart applies a console-style theme: no toolbar, inherited font, dashed horizontal grids only, no axis lines/ticks, series colors from `--om-chart-1…6`, 22% → 0 area gradients, and no point labels. Explicit business options take precedence.

Composite classes follow shell → surface → overlay → state. Shell: `oldman-sidebar`, `oldman-topbar`, `oldman-breadcrumb`, `om-page-header`, `om-page-progress`. Surface: `om-button`, `om-field`, `om-check`, `om-badge`, `om-card` (`om-table-card`, `om-form-card`, `om-stat-card`), `om-table`, `om-filter-toolbar`, `om-tabs`, `om-segmented`. Overlay: `om-dropdown-menu`, `om-tooltip-content`, `om-modal` (`om-modal-dialog-sm`, `om-confirm-*`), `om-toast`, `om-alert`. State: `om-empty`, `om-skeleton`, `om-table-empty-cell`. See [the user guide's component page](../users/components.md) for usage syntax.

Shared CSS defines variables such as `--om-color-primary`, `--om-color-border`, and `--om-shadow-card`. Application themes can override them centrally for components to consume. Changing one page's border/success color alone is not a theme update. Dark mode follows framework data-theme conventions.

The framework defines variables in `@layer base`: light on `:root`, dark on `html[data-theme="dark"]`. Override them in the same layer and locations in the project CSS entry point:

```css
@layer base {
  :root {
    --om-color-primary: var(--color-indigo-600);
  }

  html[data-theme="dark"] {
    --om-color-primary: var(--color-indigo-400);
  }
}
```

Do not place overrides outside layers. Unlayered rules override all layered rules regardless of selectors, so unlayered `:root` also overrides framework dark values and makes dark pages use light values. The dashboard scaffold's `frontend/src/app.css` ends with this commented example.

Numbered Tailwind `primary-50`, `primary-100`, `primary-500`, `primary-600`, and `primary-700` are variable aliases, not a separate fixed palette. 50/100 map to `--om-color-primary-soft`, 500 to `--om-color-focus-border`, 600 to `--om-color-primary`, and 700 to `--om-color-primary-hover`. Like `bg-primary`, they follow dark mode/project overrides. Use `text-on-primary` on primary backgrounds rather than `text-white`, because dark-mode primary is light.

## Translation is not a second frontend domain

Project Python, Jinja, App CLI, and frontend source messages merge into `messages.po`. Backend runtime uses MO; browsers use JSON. These are outputs of the same translations, without a separately maintained frontend/js domain.

### Framework translations

Framework `oldman/locales` supplies simplified `zh_Hans` and traditional `zh_Hant` translations for all framework text: built-in Admin; account pages (sign-in, profile, users, roles, password reset); tables/forms; notifications; roles; error pages; CLI/migration commands; and `oldman-web` browser messages. Lookup order is:

1. Project `locales/`;
2. Each installed App's `locales/` (third-party Apps may ship translations);
3. Framework `oldman/locales` as the final fallback.

Web and CLI share this order (`oldman.i18n.catalogs.translation_roots`). With i18n enabled and only `zh-Hans` configured, framework pages/messages are immediately Chinese regardless of Admin installation; projects translate only their own text. Projects translate unsupported languages such as Arabic: `i18n extract` includes framework text in the project POT for one-time translation. Override a framework translation in project PO to take precedence. Empty project PO entries are omitted from MO compilation and still fall back to framework translations.

Browser catalogs use the same fallback. During `i18n compile-frontend`, framework browser messages untranslated in project PO use framework catalogs. Without a project PO for the language, all framework browser messages and plural rules come from the framework. The resulting catalog still contains only frontend messages, excluding backend text.

See [source development](maintenance.md#browser-package-and-admin-builds) for maintaining framework translations.

The actual Jinja section of demo root babel.cfg:

```ini
[jinja2: templates/**.html]
encoding = utf-8
extensions=jinja2.ext.i18n,oldman.web.template.I18nExtension,oldman.web.security.csrf.CsrfExtension
silent=False
```

Retain the same file's apps/config/core/services Python scanning and .venv/node_modules/scripts/tests exclusions. This excerpt is only the Jinja section, not a replacement babel.cfg. Fix application configuration when extract encounters extension-import errors rather than disabling CSRF or silently ignoring templates.

The demo already has simplified/traditional PO files. Update them from the project root:

```sh
./run.sh i18n extract
./run.sh i18n update
# After editing locales/<locale>/LC_MESSAGES/messages.po:
./run.sh i18n compile
pnpm --dir frontend generate:i18n
```

Run `i18n init <language-code>` only for new languages. Commands use standard zh-Hans/zh-Hant codes, while Babel directories use zh_Hans/zh_Hant. Do not pass directory names directly as CLI language codes or reinitialize existing directories.

`generate:i18n` runs framework CLI `oldman i18n compile-frontend --service <service-name>`, the sole browser-catalog entry point; projects no longer carry a duplicate compiler script. The command uses four service-convention locations: `data/<service-name>_settings.yaml`, `locales/`, `frontend/public/i18n/`, and `frontend/src/i18n/generated.ts`:

1. Resolve configured languages, aliases, and default through framework I18nConfig/LanguageRegistry. Missing configuration, empty languages, or a default outside the set fail immediately.
2. Read `locales/<babel_locale>/LC_MESSAGES/messages.po` per language and compile browser catalogs.
3. Write catalogs to `frontend/public/i18n/<lowercase-language-code>.json`, such as zh-hans.json, and the language list to `frontend/src/i18n/generated.ts`, including catalogPath, aliases, flag URLs, etc.
4. Generate/validate the entire set in a temporary directory, publish catalogs, then replace the manifest. Normal failures retain matching old output. The manifest must sit outside the catalog directory or publication would replace it too; such wiring fails before building starts.
5. prebuild/predev runs this command, then Vite publishes public/i18n to static output or its development server.

The language list is an imported TypeScript module, so available languages arrive with the bundle without another startup fetch. The tradeoff is that **adding languages requires rebuilding the frontend**; i18n compilation alone is insufficient. Projects needing different paths call `oldman.web.i18n.frontend_build.build_frontend_i18n()` with all four locations explicitly.

Without PO, the language's catalog contains only framework browser messages translated by the framework (see "Framework translations" above); project browser text remains source text. This does not establish complete translation. JSON existence is not a translation check.

### Three language lists

The available-language set has three runtime sources. Only the first changes immediately after configuration changes and restart:

| List | Source | Update trigger |
| --- | --- | --- |
| User-facing switcher menu | `settings.i18n.languages` (`language_menu_items()`) | Configuration change + restart |
| Backend messages | `.mo` compiled from project `locales/`, falling back to framework `oldman/locales` | `i18n compile`; framework catalogs update with framework versions |
| Browser messages and frontend manifest | `frontend/public/i18n/` and `generated.ts` | `i18n compile-frontend` + frontend rebuild |

Changing only configuration can produce a menu language that displays msgids when selected. `ensure_frontend_catalogs(registry, bundle_name, source_dir=...)` turns this into a startup failure: every configured language must have a catalog in the collected static root. Scaffold `prepare_server` already wires it. Development instead warns against the source directory because Vite serves catalogs directly.

Built-in Admin uses a different path: its catalogs are a route under its own prefix, merging locales roots at request time so projects can override framework text. The prefix is also chosen only at installation. Neither can be pregenerated as build output. Admin extensions only add translations to project `locales/` without frontend i18n builds. Projects also translate Admin text for languages unsupported by the framework.

Extraction has three explicit sources: project Python/Jinja scanned with root babel.cfg; installed oldman Python/Jinja scanned with packaged framework-babel.cfg (including CLI, migrations, and roles; also used for framework translations); and project frontend/src TypeScript AST plus the packaged frontend message list, merged into one POT. App commands.py lazy help is extracted like other Python text when covered by project Babel rules. This does not scan every installed third-party package. Third-party Apps should publish catalogs and connect their translation roots at runtime.

Compilation filters catalogs through the framework frontend-message list and project frontend/src AST extraction, avoiding delivery of all backend messages. The list is compiler input, not another translation source or a manually maintained user file. TypeScript extraction uses static literals in `i18n.t/tc/tn/tnc`. Rewrite dynamic concatenated msgids as stable literals rather than omitting them and claiming complete extraction.

Low-level npm tools are `oldman-web-i18n extract --project-root . --source-root frontend/src` and `oldman-web-i18n compile-po --fallback-locale en` (reading PO from stdin). Ordinary projects should prefer Oldman CLI/scaffold scripts rather than another PO parser.

Demo main.ts imports defaultLanguage, languageAliases, languageDefinitions, and languagePreferencePath from `./i18n/generated` and reads the asset base from page oldman-asset-base meta. It creates createI18n, passes it to createOldmanContext, and waits for i18n.init before startOldman. See [the frontend entry point](frontend.md#demo-dashboard-page-entry-point) for complete code.

Catalog loading needs no custom implementation. `createFetchCatalogLoader` comes from oldman-web/core:

```typescript
const assetBaseUrl = readAssetBaseUrl();
const i18n = createI18n({
  aliases: languageAliases,
  catalogLoader: createFetchCatalogLoader({ assetBaseUrl }),
  defaultLanguage,
  document,
  http,
  languagePreferencePath,
  languages: languageDefinitions
});
```

Supplying `http` also requires `languagePreferencePath`, specifying where to POST language choices; generated `generated.ts` uses `i18n.preference_url`. Omitting it makes `createI18n` fail instead of guessing an address. `null` means no endpoint and suits only single-language pages (also Admin's fallback without server language data). On multilingual pages outside path mode, `null` leaves no Cookie to remember the selection when returning to the current page, reverting its language. Path mode is unaffected because the destination URL carries its language prefix.

`createFetchCatalogLoader` resolves `catalogPath` by URL rules without rewriting it. Project catalogs live with bundles and use relative `i18n/en.json` resolved against assetBaseUrl. Admin catalogs are another mounted route and use absolute site paths such as `/admin/i18n/en.json`. Stripping the leading slash would resolve them against the current page, producing 404 on every non-root page.

Production base is /static/dist/; development uses the Vite URL. Do not hardcode JSON paths to another port. HTTP/network/invalid-JSON failures all fall back to empty catalogs, letting missing translations show msgids rather than preventing startup. Fallback is not successful loading. Verify actual Network catalog requests, body translations, and switching, not merely simplified/traditional menu options.

### Which language a request uses

The server decides each request's language and writes `<html lang>`. Browser startup only reads that attribute; it neither decides independently nor reads/writes Cookies/localStorage. Server behavior splits by `i18n.use_i18n_path`:

| Mode | Language source | Suitable use |
| --- | --- | --- |
| Path mode (`use_i18n_path: true`) | Only path prefixes: `/zh-hans/...` is simplified Chinese; unprefixed paths use `i18n.default_language`. Cookies and Accept-Language are ignored | Ordinary websites: separate indexable language URLs; switching is a link, without a frontend package |
| Non-path mode (default) | Query `?lang=`, then language Cookie (`i18n.cookie_name`, default `preferred_language`), then Accept-Language, then `i18n.default_language` | Dashboards and built-in Admin |

Ordinary websites use path mode only. The framework offers no Cookie-based language memory for ordinary websites: switching would require frontend code, while the frontend package is intended for dashboards.

Language switching outside path mode:

1. The user selects a language; the browser POSTs `{"language": "<code>"}` to `i18n.preference_url` (default `/preferences/language`), available before or after sign-in.
2. `save_language_preference` handles this endpoint and is the **sole** language-Cookie writer. Its name is `i18n.cookie_name`, lifetime `i18n.cookie_max_age` (default 365 days), `Path=/`, `SameSite=Lax`, and `Secure` follows `web.session.cookie_secure`. It is not HttpOnly, allowing project scripts to read the current language.
3. The browser navigates to the menu item's URL (current page without `?lang=`), and the server renders using the new Cookie's language.

Change those two settings to customize Cookie name/lifetime; do not add another frontend Cookie implementation.

## Dashboard scaffold scope

Selecting dashboard in `startproject` generates a sign-in-ready scaffold:

- Accounts: project User (`apps/accounts/models.py`); `apps/accounts/routes.py` installs `LoginFlow`, `AccountFlow`, `UserManagementFlow`, and `RoleManagementFlow` according to `web.account` (see [ready-made account flows](web.md#ready-made-account-flows)). Every active account can sign in. User management requires `auth.users.*`; role management requires `roles.*`.
- Home `apps/home` (`/`, requiring sign-in), shell `templates/base.html`, and menus only in `templates/partials/sidebar.html`. User management appears only with `auth.users.view`, roles only with `roles.view`, through registered `can_manage_users`/`can_manage_roles` template functions.
- Services install CSRF, notifications, templates/frontend bundles, then account pages. Projects selecting built-in Admin additionally install `/admin` and show its sidebar link to staff.
- The frontend starts with framework `startDashboard`; `frontend/src/pages/base-page.ts` is the shared page class.
- Configuration enables Sessions (requiring Redis), sets `core.site_name` to the project name, and installs auth, roles, notifications, `apps.accounts`, and `apps.home`.

Account templates live in the framework (`oldman/dashboard/account/*`). Replace them through matching project `templates/` paths. Generate business Apps with dashboard `startapp`; views require sign-in by default. Add sidebar items manually and register the App in service settings.

For new dashboard projects, follow the generated README. Existing API projects can add a minimal frontend entry following this chapter/tutorial without recreating the project, changing database identity, or copying the entire demo.

<!-- source: zh/developers/assets.md @ 6a3c1971 -->
