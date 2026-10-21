// 首页。文字都取自 README（docs/public 之外唯一面向所有人的介绍）和文档本身，不另写一套宣传文案；
// 中文译文在 i18n/zh-Hans/code.json（繁体由它转换生成）。版式与配色跟文档页同一套 token（src/css/custom.css）。

import CodeBlock from "@theme/CodeBlock";
import Layout from "@theme/Layout";
import ThemedImage from "@theme/ThemedImage";
import useBaseUrl from "@docusaurus/useBaseUrl";
import Link from "@docusaurus/Link";
import Translate, { translate } from "@docusaurus/Translate";
import styles from "./index.module.css";

const REPOSITORY = "https://github.com/alexliyu7352/oldman";

// README「最短的项目入口」：选 api、none 之后的完整命令。
const QUICK_START = `curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.13 oldman
oldman startproject my_site
cd my_site
uv sync
./run.sh api settings sync
./run.sh api start`;

const CAPABILITIES = [
  {
    term: translate({ id: "home.capabilities.structure.term", message: "Application structure" }),
    text: translate({
      id: "home.capabilities.structure.text",
      message:
        "A project can hold several services. Each service reads its own YAML and installs the Apps it needs; an App can provide models, views, custom commands and typed settings.",
    }),
  },
  {
    term: translate({ id: "home.capabilities.web.term", message: "Web and data" }),
    text: translate({
      id: "home.capabilities.web.text",
      message: "Async services on Sanic, Jinja HTML, SQLAlchemy models, project-level Alembic commands, authentication and the built-in Admin.",
    }),
  },
  {
    term: translate({ id: "home.capabilities.pages.term", message: "Page interaction" }),
    text: translate({
      id: "home.capabilities.pages.text",
      message:
        "Server-side forms and HTML or JSON tables, shared browser components for forms, modals, feedback, selects and charts, and ordered JSON response actions.",
    }),
  },
  {
    term: translate({ id: "home.capabilities.messages.term", message: "Messages" }),
    text: translate({
      id: "home.capabilities.messages.text",
      message:
        "One-time cookie messages, notifications kept in the database, temporary live pushes and general SSE delivery to the browser. Process control messages have their own path.",
    }),
  },
  {
    term: translate({ id: "home.capabilities.foundations.term", message: "Foundations" }),
    text: translate({
      id: "home.capabilities.foundations.text",
      message: "File storage, an HTTP client, caching, Redis and NATS providers, logging, short-lived subprocesses and persistent workers.",
    }),
  },
  {
    term: translate({ id: "home.capabilities.tasks.term", message: "Durable tasks" }),
    text: translate({
      id: "home.capabilities.tasks.text",
      message:
        "Taskiq with NATS JetStream and Redis: async functions sent as tasks, several worker processes, results, broadcasts and schedules, kept apart from local workers and Core NATS events and RPC.",
    }),
  },
  {
    term: translate({ id: "home.capabilities.mcp.term", message: "MCP server" }),
    text: translate({
      id: "home.capabilities.mcp.text",
      message:
        "Apps declare MCP tools, resources and prompts, and the Web service offers them to AI agents behind the same authentication and permissions.",
    }),
    to: "/docs/developers/mcp",
  },
];

const PACKAGES = [
  {
    name: "oldman",
    where: "PyPI",
    href: "https://pypi.org/project/oldman/",
    text: translate({
      id: "home.packages.oldman",
      message:
        "Applications, the App registry, settings, database migrations, Web, authentication, the built-in Admin, forms, templates, storage and background work.",
    }),
  },
  {
    name: "oldman-web",
    where: "npm",
    href: "https://www.npmjs.com/package/oldman-web",
    text: translate({
      id: "home.packages.oldmanWeb",
      message: "Page and component lifecycle, the dashboard layout, shared styles, forms, tables, modals and browser interaction.",
    }),
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
        "A complete business dashboard on the dashboard skeleton: sign-in, profile, notifications, user management, password reset and token endpoints, plus UI and feature examples.",
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
          <Translate id="home.hero.title">Dashboards, admin sites, APIs and background services in Python</Translate>
        </h1>
        <p className={styles.lead}>
          <Translate id="home.hero.lead">
            Oldman renders on the server. Python owns configuration, the application lifecycle, permissions, data and HTML; the browser
            handles partial updates, form submission, tables, modals and live updates. Write only the backend, or add TypeScript to the
            pages that need it.
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
        <Translate id="home.showcase.caption">The channel list in the EPG dashboard demo, on the framework's dashboard shell and table components.</Translate>
      </figcaption>
    </figure>
  );
}

function Capabilities() {
  return (
    <section className={styles.section} aria-labelledby="capabilities">
      <div className={styles.sectionHead}>
        <h2 id="capabilities" className={styles.sectionTitle}>
          <Translate id="home.capabilities.title">What the framework provides</Translate>
        </h2>
        <p className={styles.sectionText}>
          <Translate id="home.capabilities.text">
            Built on Sanic, SQLAlchemy, Alembic, Jinja and WTForms. Oldman adds the wiring between them and the application features
            on top, not a second set of foundations.
          </Translate>
        </p>
      </div>
      <dl className={styles.capabilities}>
        {CAPABILITIES.map(({ term, text, to }) => (
          <div key={term} className={styles.capability}>
            <dt>{to ? <Link to={to}>{term}</Link> : term}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Packages() {
  return (
    <section className={`${styles.section} ${styles.sectionWide}`} aria-labelledby="packages">
      <div className={styles.sectionHead}>
        <h2 id="packages" className={styles.sectionTitle}>
          <Translate id="home.packages.title">Two packages, one protocol</Translate>
        </h2>
        <p className={styles.sectionText}>
          <Translate id="home.packages.text">
            The built-in Admin and your own dashboards use the same components, styles and response protocol, so there is one frontend
            to maintain. A plain API needs only the Python package.
          </Translate>
        </p>
      </div>
      <div className={styles.packages}>
        {PACKAGES.map(({ name, where, href, text }) => (
          <div key={name} className={styles.package}>
            <p className={styles.packageName}>
              <code>{name}</code>
              <Link className={styles.packageWhere} href={href}>
                {where}
              </Link>
            </p>
            <p className={styles.packageText}>{text}</p>
          </div>
        ))}
      </div>
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
        message: "Oldman is a server-rendered-first Python framework for dashboards, admin sites, Web and API services, and background services.",
      })}
    >
      <main className={styles.page}>
        <Hero />
        <Showcase />
        <Capabilities />
        <Packages />
        <Guides />
        <Demos />
      </main>
    </Layout>
  );
}
