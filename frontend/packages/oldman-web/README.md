# oldman-web

English | [简体中文](https://github.com/alexliyu7352/oldman/blob/main/frontend/packages/oldman-web/README.zh-CN.md)

Oldman's TypeScript browser package provides shared Page lifecycles, a dashboard shell, Form, Table, Modal, response actions, an SSE client, and default styles. It uses native DOM and requires neither React nor Vue. It includes no business data, backend routes, or business pages.

The Python package oldman provides server-side models, forms, Tables, templates, and permissions. Both sides use the same HTML/JSON protocol. Admin and business dashboards share this package without separate component sets.

## Installation

Use Node.js 20 or later. In the application's frontend directory:

```sh
pnpm add oldman-web @fontsource/dm-sans
pnpm add -D vite@^5 tailwindcss@^4 @tailwindcss/vite typescript @types/node sass
```

Tailwind 4 powers the shared theme; applications that do not import shared CSS can omit it. Sass is an application build tool required by Vite to compile component SCSS. With pnpm's isolated dependencies or linked installations, do not rely on transitive dependencies happening to resolve. oldman-web declares component plugins such as TanStack, Choices, and Swiper; consumers need not reinstall them. Declare direct dependencies only when business code calls their APIs directly.

Use a version matching the Python framework. A local source link requires valid dist output in the target package; linking unbuilt src alone is insufficient. A successful installation does not create backend routes.

## Minimal dashboard entry point

This is a minimal single-page **API wiring reference**, not a source excerpt from the complete demo. For an actual entry point with translation catalogs and on-demand Page loaders, see [EPG main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) and the [Pages, components, and dynamic content](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/developers/frontend.md). The file here is the application's frontend/src/main.ts:

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

HTML uses body data-om-page="tasks" and loads scripts and styles built from this entry point. setupPage registers the class; the runtime owns the current instance. Call startOldman once per document, without restarting it in each fragment or Modal.

createDashboardComponentLoaders provides the complete default loaders with Dashboard Modal/Feedback theme adapters. createDashboardCrudComponentLoaders is a smaller subset containing only Sidebar/Table. Do not use that two-loader entry point when you need Form, Modal, or other components.

The minimal entry point does not load project translation JSON. Complete language switching uses createI18n, createOldmanContext, and catalogLoader; dashboard project scaffolds already provide this wiring.

## Styles and fonts

The layout uses frontend/src/app.css and project-root templates/ and apps/:

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

Paths are relative to the CSS file. Shared package styles already include framework classes; applications still need to scan templates, Python, and TypeScript that emit classes. Styles provide semantic classes such as om-card, om-button, and om-modal and shared visual variables, without replacing JS loaders.

DM Sans covers Latin characters. Simplified and traditional Chinese fall back to system fonts. No large Chinese font is downloaded by default; applications needing consistent Chinese glyphs choose a suitable font themselves. Override shared color, border, and spacing variables centrally, rather than redefining styles per page.

## Icons

ri-*, mdi-*, and bx-* are supported. Shared icons.css includes only framework icons. Generate application icons from actual usage:

```sh
pnpm exec oldman-web-icons --output src/generated/icons.css \
  --source src --source ../templates --source ../apps --exclude-shared
```

Add this command to application prebuild/predev/pretypecheck. The generator bundles icon data, scans complete class strings, and excludes directories such as tests, vendor, theme, public, static, and dist. It cannot infer every icon from dynamically concatenated strings. Committing the generated file provides a CSS import target immediately after checkout.

Complete catalogs: [Remix Icon](https://icon-sets.iconify.design/ri/), [Material Design Icons](https://icon-sets.iconify.design/mdi/), and [BoxIcons](https://icon-sets.iconify.design/bx/). For example, ri-add-line. Decorative icons use aria-hidden; icon-only buttons still require aria-label.

## Public entry points and dynamic content

| Import | Purpose |
| --- | --- |
| oldman-web/core | Page, Component, runtime, HTTP, i18n, actions, and types |
| oldman-web/app | BasePage and dynamic page lifecycles |
| oldman-web/dashboard | DashboardPage, shell, and loaders |
| oldman-web/dashboard/modal, oldman-web/dashboard/feedback | Shared dashboard/Admin theme adapters |
| oldman-web/components/form, table, select, etc. | Individual components and public types |
| oldman-web/sse | Browser SSE client |

Do not import deep private src/dist files. Page manages components. Dynamic HTML first unmounts old components, then loads and mounts new ones. Leaving the page releases requests, listeners, and plugin instances.

Modal is only a container; an ordinary Form still submits its internal form. Remote loadParts consumes title/body/footer JSON; loadContent consumes HTML. Form and the current Page's Runner consume actions JSON after saving. Do not confuse these protocols. Calling setContent/setParts directly does not replace the complete dynamic loading lifecycle.

Declarative remote content opens the Modal only after successful loading. On failure, the shared click entry point reports through the owning Page's Feedback, retaining error state and the om:modal:error event. Applications need no additional listener to show another alert. Cancellation on leaving/destroying a page shows no error. Direct loadParts/loadContent calls still raise the original exception for callers to handle. A standalone low-level Modal without a Page only logs declarative failures; it creates no global Feedback, and hidden container state is not itself visible. See the Page reference below for complete entry points and event types.

JSON Table uses the shared server columns/rows/pagination/sort protocol; HTML Table consumes server fragments. Both refresh through reload. Do not treat either as an arbitrary third-party table protocol.

DashboardPage provides default Feedback. Toasts use Toastify; modals use SweetAlert2, both through the Feedback API. Displaying a toast does not automatically create a persistent notification record.

## Translation

Project Python, Jinja, CLI, and browser code share messages PO files. The browser receives JSON containing only required entries:

```sh
# Extract TypeScript from the project root; higher-level tools merge the output.
frontend/node_modules/.bin/oldman-web-i18n extract --project-root . --source-root frontend/src
# Read PO from stdin and write catalog JSON to stdout.
frontend/node_modules/.bin/oldman-web-i18n compile-po --fallback-locale en < locales/en/LC_MESSAGES/messages.po
```

extract uses the TypeScript AST to recognize i18n.t/tc/tn/tnc and accepts string literals or template literals without interpolation. Dynamic messages, missing arguments, and syntax errors report precise file locations. compile-po preserves context, plural forms, and pluralRule. Projects should not write another PO parser.

The Python CLI manages project-wide POT/PO/MO. Dashboard scaffold build scripts filter JSON using framework and project frontend message inventories, then publish through Vite. The low-level compile-po command does not automatically know which messages belong to the frontend.

## Full documentation

[Demo HTML/JSON tables and Modal forms](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/tutorial-dashboard.md) · [Dashboard UI and interactive components](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/components.md) · [Pages, components, and dynamic content](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/developers/frontend.md) · [Browser responses and ordered actions](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/developers/responses.md) · [Frontend assets, styles, icons, and translation](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/developers/assets.md)

The release includes dist, icon and translation CLIs, type declarations, README, and LICENSE. Applications build their own entry points; backend built-in Admin assets do not replace business frontend builds.

<!-- source: frontend/packages/oldman-web/README.zh-CN.md @ 7dfc0480 -->
