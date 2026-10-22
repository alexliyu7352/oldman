// 首页。卖点、比较表和性能数据与 README 一致（README.zh-CN.md 是中文源，README.md 是英文）；改其中一处时两边一起改。
// 中文译文在 i18n/zh-Hans/code.json（繁体由它转换生成）。版式与配色跟文档页同一套 token（src/css/custom.css）。

import CodeBlock from "@theme/CodeBlock";
import Layout from "@theme/Layout";
import ThemedImage from "@theme/ThemedImage";
import useBaseUrl from "@docusaurus/useBaseUrl";
import Link from "@docusaurus/Link";
import Translate, { translate } from "@docusaurus/Translate";
import styles from "./index.module.css";

const REPOSITORY = "https://github.com/alexliyu7352/oldman";

// README「快速开始」：选 api、none 之后的完整命令。
const QUICK_START = `curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.13 oldman
oldman startproject my_site
cd my_site
uv sync
./run.sh api settings sync
./run.sh api start`;

// 以下几段代码照抄文档与 EPG 示例的原文（节选），不为首页另写一份；ModelAdmin 那行太长，只在这里换了行。
const SERVICES_EXAMPLE = `./run.sh web start             # dashboard, Admin, token API, MCP
./run.sh task_worker start     # Taskiq workers
./run.sh task_scheduler start  # scheduled tasks
./run.sh nats_a start          # NATS events and RPC`;

const ADMIN_EXAMPLE = `class DemoProjectAdmin(ModelAdmin):
    list_display = (
        "id", "name", "owner", "status", "is_active", "created_at",
    )
    search_fields = ("name", "owner", "status")
    ordering = ("name",)`;

const TABLE_EXAMPLE = `class ChannelsEpgTable(SQLAlchemyTableView):
    route_path = "/channels-epg/table"
    model = ChannelsEpg
    page_size = 10
    selectable = True
    export_formats = ("csv",)
    search_fields = ["name", "src_url", "country"]
    columns = [
        (_("ID"), "id"),
        (_("Name"), "name"),
        (_("Source URL"), "src_url", "get_column_src_url_data"),
        (_("Country"), "country"),
        (_("Hits"), "hits"),
        (_("Last Date"), "last_date"),
        (_("Action"), None, "get_column_action_data"),
    ]`;

const MCP_EXAMPLE = `@mcp.tool(permission=ReportPermissions.view)
async def count_reports(request: Request, status: str) -> int:
    """Count reports in one status."""
    async with db_manager.get_read_session() as session:
        ...`;

// 2026-10-21 实测（docs/internal/2026-10-21-positioning-and-benchmark.md）：1 个 worker、oha 64 连接、3 轮各 15 秒取中位数。
const BENCHMARK = [
  {
    name: "Oldman 0.8.0",
    note: translate({ id: "home.fast.oldman", message: "every request goes through the authentication pipeline" }),
    rps: 20300,
    p99: "6.1",
    ours: true,
  },
  { name: "Sanic 25.12", note: translate({ id: "home.fast.sanic", message: "used directly" }), rps: 17900, p99: "6.8" },
  {
    name: "FastAPI 0.159 + uvicorn",
    note: translate({ id: "home.fast.fastapiOrjson", message: "responses encoded with orjson" }),
    rps: 13000,
    p99: "9.2",
  },
  { name: "FastAPI 0.159 + uvicorn", note: translate({ id: "home.fast.fastapi", message: "default style" }), rps: 11100, p99: "10.7" },
];

const COMPARISON = [
  {
    need: translate({ id: "home.compare.admin.need", message: "An admin site" }),
    usual: translate({ id: "home.compare.admin.usual", message: "Django's built-in admin; with FastAPI, a third-party library such as SQLAdmin" }),
    oldman: translate({ id: "home.compare.admin.oldman", message: "The built-in Admin, sharing one UI with your own pages" }),
  },
  {
    need: translate({ id: "home.compare.accounts.need", message: "A back office with accounts and permissions" }),
    usual: translate({ id: "home.compare.accounts.usual", message: "Build the pages yourself or adapt a frontend template" }),
    oldman: translate({ id: "home.compare.accounts.oldman", message: "startproject generates sign-in, user, role and permission management" }),
  },
  {
    need: translate({ id: "home.compare.pages.need", message: "Interactive pages" }),
    usual: translate({ id: "home.compare.pages.usual", message: "A separate React or Vue frontend, or wiring htmx yourself" }),
    oldman: translate({ id: "home.compare.pages.oldman", message: "Tables, forms and modals declared in Python, on shared components" }),
  },
  {
    need: translate({ id: "home.compare.tasks.need", message: "Durable tasks" }),
    usual: translate({ id: "home.compare.tasks.usual", message: "Add a task queue such as Celery" }),
    oldman: translate({ id: "home.compare.tasks.oldman", message: "Taskiq on NATS JetStream, built in" }),
  },
  {
    need: translate({ id: "home.compare.messaging.need", message: "Events and RPC between services" }),
    usual: translate({ id: "home.compare.messaging.usual", message: "Pick a messaging library and wire it yourself" }),
    oldman: translate({ id: "home.compare.messaging.oldman", message: "NATS events and RPC, built in" }),
  },
  {
    need: translate({ id: "home.compare.ops.need", message: "Terminal ops tools" }),
    usual: translate({ id: "home.compare.ops.usual", message: "Separate Click or Typer scripts" }),
    oldman: translate({ id: "home.compare.ops.oldman", message: "The same App commands, with terminal menus and forms" }),
  },
  {
    need: translate({ id: "home.compare.agents.need", message: "An interface for AI agents" }),
    usual: translate({ id: "home.compare.agents.usual", message: "Install the MCP SDK and wire authentication yourself" }),
    oldman: translate({ id: "home.compare.agents.oldman", message: "A built-in MCP server on your existing authentication and permissions" }),
  },
];

const GUIDES = [
  {
    to: "/docs/users",
    title: translate({ id: "home.guides.users.title", message: "User Guide" }),
    text: translate({ id: "home.guides.users.text", message: "Install, create a project and put it to use." }),
  },
  {
    to: "/docs/developers",
    title: translate({ id: "home.guides.developers.title", message: "Developer Reference" }),
    text: translate({ id: "home.guides.developers.text", message: "Exact interfaces, load order and extension points." }),
  },
  {
    to: "/docs/agents",
    title: translate({ id: "home.guides.agents.title", message: "Agent Guide" }),
    text: translate({ id: "home.guides.agents.text", message: "For coding agents: which files to change for a task, how to wire them and how to verify." }),
  },
  {
    to: "/docs/api",
    title: translate({ id: "home.guides.api.title", message: "API Reference" }),
    text: translate({ id: "home.guides.api.text", message: "Every public name with its signature, summary and the module that defines it." }),
  },
];

const DEMOS = [
  {
    name: translate({ id: "home.demos.epg.name", message: "EPG dashboard" }),
    repository: "oldman-epg-dashboard",
    text: translate({
      id: "home.demos.epg.text",
      message:
        "A complete business back office on the dashboard skeleton: accounts, notifications, user and role management, plus UI and feature examples.",
    }),
  },
  {
    name: translate({ id: "home.demos.admin.name", message: "Built-in Admin" }),
    repository: "oldman-admin-demo",
    text: translate({
      id: "home.demos.admin.text",
      message: "The built-in Admin as an application of its own, on SQLite with Redis sessions and the same oldman-web components.",
    }),
  },
  {
    name: translate({ id: "home.demos.ops.name", message: "Ops tool" }),
    repository: "oldman-ops-demo",
    text: translate({
      id: "home.demos.ops.text",
      message: "A server maintenance tool with numbered terminal menus: it edits sshd, sysctl and nginx sites, restarts services and cleans up operation records in the database.",
    }),
  },
];

function Hero() {
  return (
    <header className={styles.hero}>
      <div className={styles.heroText}>
        <h1 className={styles.title}>
          <Translate id="home.hero.title">One Python framework for the whole back end</Translate>
        </h1>
        <p className={styles.lead}>
          <Translate id="home.hero.lead">
            Dashboards, the admin site, APIs, background jobs, messaging between services, terminal ops tools and an MCP endpoint for
            AI agents share one set of settings, permissions and UI. It runs on Sanic and serves about 1.8 times as many requests per
            second as FastAPI.
          </Translate>
        </p>
        <div className={styles.actions}>
          <Link className="button button--primary button--lg" to="/docs/users/getting-started">
            <Translate id="home.hero.start">Get started</Translate>
          </Link>
          <Link className="button button--secondary button--outline button--lg" href={REPOSITORY}>
            <Translate id="home.hero.github">View on GitHub</Translate>
          </Link>
        </div>
        <p className={styles.requirements}>
          <Translate id="home.hero.requirements">Linux · Python 3.12 to 3.14 · MIT license</Translate>
        </p>
      </div>
      <div className={styles.heroCode}>
        <CodeBlock language="sh" title={translate({ id: "home.quickStart.title", message: "A new API project" })}>
          {QUICK_START}
        </CodeBlock>
        <p className={styles.caption}>
          <Translate id="home.quickStart.caption">
            Choose api and none when startproject asks for the project type and the database. The service answers on / without
            credentials; its README shows how to call the two endpoints that need an API key or a password.
          </Translate>
        </p>
      </div>
    </header>
  );
}

// 截图来自 EPG Dashboard 示例（/channels-epg），亮暗各一张，1440×900 视口、2 倍像素。界面改版后重新截取。
function Showcase() {
  return (
    <figure className={styles.showcase}>
      <ThemedImage
        className={styles.showcaseImage}
        alt={translate({
          id: "home.showcase.alt",
          message:
            "The channel list of the EPG dashboard demo: a table with search, column, density and export menus, country badges and pagination, in the dashboard shell with its sidebar.",
        })}
        sources={{ light: useBaseUrl("/img/epg-channels-light.webp"), dark: useBaseUrl("/img/epg-channels-dark.webp") }}
        width={2880}
        height={1800}
      />
      <figcaption className={styles.showcaseCaption}>
        <Translate id="home.showcase.caption">
          The channel list in the EPG dashboard demo. The table, with its search, sorting, export and pagination, is the Python class
          shown further down.
        </Translate>
      </figcaption>
    </figure>
  );
}

/** 一个卖点：左文右图，`flip` 时左右互换，相邻两段不同版式。 */
function Feature({ id, title, children, visual, flip = false }) {
  return (
    <section className={`${styles.feature} ${flip ? styles.featureFlip : ""}`} aria-labelledby={id}>
      <div className={styles.featureText}>
        <h3 id={id} className={styles.featureTitle}>
          {title}
        </h3>
        {children}
      </div>
      <div className={styles.featureVisual}>{visual}</div>
    </section>
  );
}

function Benchmark() {
  const top = Math.max(...BENCHMARK.map(({ rps }) => rps));
  return (
    <figure className={styles.bench}>
      <figcaption className={styles.benchTitle}>
        <Translate id="home.fast.chartTitle">Requests per second, one worker, the same JSON response</Translate>
      </figcaption>
      <ol className={styles.benchRows}>
        {BENCHMARK.map(({ name, note, rps, p99, ours }) => (
          <li key={`${name} ${note}`} className={`${styles.benchRow} ${ours ? styles.benchOurs : ""}`}>
            <span className={styles.benchLabel}>
              <span className={styles.benchName}>{name}</span>
              <span className={styles.benchNote}>{note}</span>
            </span>
            <span className={styles.benchTrack} aria-hidden="true">
              <span className={styles.benchBar} style={{ width: `${(rps / top) * 100}%` }} />
            </span>
            <span className={styles.benchValue}>
              {rps.toLocaleString("en-US")}
              <span className={styles.benchLatency}>p99 {p99} ms</span>
            </span>
          </li>
        ))}
      </ol>
      <p className={styles.benchMethod}>
        <Translate id="home.fast.method">
          One AMD Ryzen 7 3800X, Python 3.13.11. Each service ran one worker pinned to the same CPU; oha with 64 connections ran three
          15-second rounds, and the median is shown. uvicorn used uvloop and httptools; Oldman was the API project startproject
          generates, unchanged. This measures framework overhead only: in real applications the database and outside calls usually
          dominate.
        </Translate>
      </p>
    </figure>
  );
}

function Why() {
  return (
    <section className={styles.why} aria-labelledby="why">
      <h2 id="why" className={`${styles.sectionTitle} ${styles.whyTitle}`}>
        <Translate id="home.why.title">Why Oldman</Translate>
      </h2>

      <Feature
        id="why-one"
        title={translate({ id: "home.one.title", message: "One framework for the whole back end" })}
        visual={
          <CodeBlock language="sh" title={translate({ id: "home.one.codeTitle", message: "One project, four services: the EPG demo" })}>
            {SERVICES_EXAMPLE}
          </CodeBlock>
        }
      >
        <p className={styles.featureLead}>
          <Translate id="home.one.text">
            A project runs several services. Each reads its own YAML and installs the Apps it needs, and all of them share one typed
            settings model, the same models, permissions and lifecycle.
          </Translate>
        </p>
        <ul className={styles.featureList}>
          <li>
            <Translate id="home.one.web">Business dashboards and the built-in Admin, rendered on the server</Translate>
          </li>
          <li>
            <Translate id="home.one.api">APIs behind one authentication pipeline: sessions, JWT, API keys, HTTP Basic, IP allowlists</Translate>
          </li>
          <li>
            <Translate id="home.one.background">Background work, and durable Taskiq tasks with results, broadcasts and schedules</Translate>
          </li>
          <li>
            <Translate id="home.one.messaging">NATS events and RPC between services</Translate>
          </li>
          <li>
            <Translate id="home.one.ops">Terminal ops tools with menus, forms and an unattended mode</Translate>
          </li>
          <li>
            <Translate id="home.one.mcp">An MCP server for AI agents</Translate>
          </li>
        </ul>
      </Feature>

      <Feature
        id="why-backoffice"
        flip
        title={translate({ id: "home.backoffice.title", message: "A complete back office out of the box" })}
        visual={
          <CodeBlock language="python" title={translate({ id: "home.backoffice.codeTitle", message: "A model in the built-in Admin" })}>
            {ADMIN_EXAMPLE}
          </CodeBlock>
        }
      >
        <p className={styles.featureLead}>
          <Translate id="home.backoffice.text">
            Choose the dashboard type in startproject and the project starts with sign-in, a profile page, a notification center, user
            management, and role and permission management, with the frontend build and the shared UI already wired. Password reset and
            token endpoints are one ready-made flow each.
          </Translate>
        </p>
        <p className={styles.featureLead}>
          <Translate id="home.backoffice.admin">
            The built-in Admin works like Django admin: register a model to get its list, search, sorting, create, edit, delete and CSV
            export, with no frontend build.
          </Translate>
        </p>
      </Feature>

      <Feature
        id="why-pages"
        title={translate({ id: "home.pages.title", message: "Interactive pages with little frontend code" })}
        visual={
          <CodeBlock language="python" title={translate({ id: "home.pages.codeTitle", message: "The table in the screenshot (excerpt)" })}>
            {TABLE_EXAMPLE}
          </CodeBlock>
        }
      >
        <p className={styles.featureLead}>
          <Translate id="home.pages.text">
            Tables, forms, modals, charts and live updates are declared in Python. The browser components come from oldman-web, which
            mounts and cleans them up as pages change, so you write TypeScript only where a page really needs it.
          </Translate>
        </p>
        <p className={styles.featureLead}>
          <Translate id="home.pages.shared">
            The built-in Admin and your dashboards use the same components, styles and response protocol: one frontend to maintain.
          </Translate>
        </p>
      </Feature>

      <Feature
        id="why-ai"
        flip
        title={translate({ id: "home.ai.title", message: "Built for the AI era" })}
        visual={
          <CodeBlock language="python" title={translate({ id: "home.ai.codeTitle", message: "An MCP tool behind a permission" })}>
            {MCP_EXAMPLE}
          </CodeBlock>
        }
      >
        <p className={styles.featureLead}>
          <Translate id="home.ai.mcp">
            Apps declare MCP tools, resources and prompts with decorators. The Web service offers them to AI agents such as Claude Code
            and Cursor behind the same authentication, permissions and rate limits, as one more route: no second server and no
            dependency on the official SDK.
          </Translate>
        </p>
        <p className={styles.featureLead}>
          <Translate id="home.ai.agents">
            Every generated project has an AGENTS.md, and the framework has English agent guides and an API index generated from the
            source, so a coding agent can wire new features correctly.
          </Translate>
        </p>
        <Link to="/docs/developers/mcp">
          <Translate id="home.ai.link">How the MCP server works</Translate>
        </Link>
      </Feature>

      <Feature
        id="why-fast"
        title={translate({ id: "home.fast.title", message: "Fast" })}
        visual={<Benchmark />}
      >
        <p className={styles.featureLead}>
          <Translate id="home.fast.text">
            The speed comes from Sanic, and Oldman's authentication and middleware add next to no overhead on top of it: Oldman serves
            about 1.8 times the requests per second of FastAPI's default style, and 1.6 times FastAPI with orjson.
          </Translate>
        </p>
      </Feature>
    </section>
  );
}

function Comparison() {
  const usualLabel = translate({ id: "home.compare.usual", message: "The usual way" });
  return (
    <section className={`${styles.section} ${styles.sectionWide}`} aria-labelledby="compare">
      <div className={styles.sectionHead}>
        <h2 id="compare" className={styles.sectionTitle}>
          <Translate id="home.compare.title">Compared with the usual stack</Translate>
        </h2>
        <p className={styles.sectionText}>
          <Translate id="home.compare.text">What a business back end usually needs, how it is usually assembled, and what Oldman ships with.</Translate>
        </p>
      </div>
      {/* 窄屏上表格改成每行一块，data-label 给单元格补上列名。 */}
      <table className={styles.compare}>
        <thead>
          <tr>
            <th scope="col">
              <Translate id="home.compare.need">You need</Translate>
            </th>
            <th scope="col">{usualLabel}</th>
            <th scope="col">Oldman</th>
          </tr>
        </thead>
        <tbody>
          {COMPARISON.map(({ need, usual, oldman }) => (
            <tr key={need}>
              <th scope="row">{need}</th>
              <td data-label={usualLabel}>{usual}</td>
              <td data-label="Oldman" className={styles.compareOurs}>
                {oldman}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Guides() {
  return (
    <section className={styles.section} aria-labelledby="guides">
      <div className={styles.sectionHead}>
        <h2 id="guides" className={styles.sectionTitle}>
          <Translate id="home.guides.title">Read the documentation</Translate>
        </h2>
      </div>
      <ul className={styles.guides}>
        {GUIDES.map(({ to, title, text }) => (
          <li key={to}>
            <Link className={styles.guide} to={to}>
              <span className={styles.guideTitle}>{title}</span>
              <span className={styles.guideText}>{text}</span>
              <span className={styles.guideArrow} aria-hidden="true">
                →
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Demos() {
  return (
    <section className={`${styles.section} ${styles.sectionWide}`} aria-labelledby="demos">
      <div className={styles.sectionHead}>
        <h2 id="demos" className={styles.sectionTitle}>
          <Translate id="home.demos.title">Complete examples</Translate>
        </h2>
        <p className={styles.sectionText}>
          <Translate id="home.demos.text">
            Each example is a Git repository of its own, with its settings, virtual environment, frontend dependencies and database.
          </Translate>
        </p>
      </div>
      <div className={styles.demos}>
        {DEMOS.map(({ name, repository, text }) => (
          <div key={repository} className={styles.demo}>
            <h3 className={styles.demoName}>{name}</h3>
            <p className={styles.demoText}>{text}</p>
            <Link className={styles.demoLink} href={`https://github.com/alexliyu7352/${repository}`}>
              {`alexliyu7352/${repository}`}
            </Link>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Home() {
  return (
    <Layout
      description={translate({
        id: "home.meta.description",
        message:
          "Oldman is one Python framework for the whole back end: dashboards, the admin site, APIs, background jobs, messaging between services, terminal ops tools and an MCP endpoint for AI agents.",
      })}
    >
      <main className={styles.page}>
        <Hero />
        <Showcase />
        <Why />
        <Comparison />
        <Demos />
        <Guides />
      </main>
    </Layout>
  );
}
