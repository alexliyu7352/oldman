// 文档站配置。内容不在这里，也不属于这里：源是 docs/public/<语言>/，
// scripts/build-docs-site.py 把它组装成 Docusaurus 要的形状后放进暂存树。
// 这个文件是唯一知道 Docusaurus 形状的地方之一，仓库结构不跟着它走。
//
// 外观跟框架的界面是一套：石板灰单色、蓝色链接、品牌标那道蓝到绿的渐变只用在品牌标上，
// 数值来自框架的设计规格（oldman-web 的 tailwind.css 里的 --om-* token），见 src/css/custom.css。

import { themes } from "prism-react-renderer";

const ORGANIZATION = "alexliyu7352";
const PROJECT = "oldman";
const REPOSITORY = `https://github.com/${ORGANIZATION}/${PROJECT}`;

/** 暂存目录名 -> 源目录名。editUrl 要指回真实的源文件，不是暂存副本。 */
const SOURCE_DIRECTORY = { en: "en", "zh-Hans": "zh" };

/** 代码块底色跟页面的表面色走（亮：slate-50，暗：slate-900），高亮配色沿用 Prism 自带的两套。 */
const CODE_LIGHT = { ...themes.github, plain: { ...themes.github.plain, backgroundColor: "#f8fafc" } };
const CODE_DARK = { ...themes.vsDark, plain: { ...themes.vsDark.plain, backgroundColor: "#0f172a" } };

export default {
  title: "Oldman",
  tagline: "A server-rendered-first Python framework for dashboards, admin sites, Web and API services, and background services",
  favicon: "img/logo.svg",

  url: `https://${ORGANIZATION}.github.io`,
  baseUrl: `/${PROJECT}/`,
  organizationName: ORGANIZATION,
  projectName: PROJECT,
  trailingSlash: false,

  // 死链一律失败。文档跨语言、跨目录互链很多，静默的 404 比构建失败难查得多。
  onBrokenLinks: "throw",
  onBrokenAnchors: "warn",
  markdown: {
    // .md 当成 CommonMark/GFM，不当成 MDX。这些文档是写给 GitHub 读者的，
    // 里面有 `<400`、`Dict[str, Any]` 这类裸尖括号和花括号；MDX 会把它们当 JSX 解析
    // 而报错。要 MDX 的页面另存成 .mdx 即可。
    format: "detect",
    hooks: {
      onBrokenMarkdownLinks: "throw",
    },
  },

  i18n: {
    // 英文不带路径前缀。两棵暂存树都是完整的，所以这不依赖 Docusaurus 自己的
    // 回退——缺的译文在组装阶段就用中文填上了，站点侧不存在“未翻译”状态。
    defaultLocale: "en",
    locales: ["en", "zh-Hans"],
    localeConfigs: {
      en: { label: "English" },
      "zh-Hans": { label: "简体中文" },
    },
  },

  presets: [
    [
      "classic",
      {
        docs: {
          path: ".staging/en",
          // 首页是 src/pages/index.js，文档在 /docs/ 下。
          routeBasePath: "docs",
          sidebarPath: "./sidebars.js",
          // 指回 docs/public/<语言>/ 的真实文件。暂存副本不在 git 里，链过去没有意义。
          editUrl: ({ locale, docPath }) =>
            `${REPOSITORY}/edit/main/docs/public/${SOURCE_DIRECTORY[locale] ?? locale}/${docPath}`,
          // 暂存树是每次构建新拷出来的，git 时间戳对它无效，显示出来会是错的。
          showLastUpdateTime: false,
        },
        blog: false,
        theme: {
          customCss: "./src/css/custom.css",
        },
      },
    ],
  ],

  themeConfig: {
    // 跟随系统的亮暗设置；用户切换后由 Docusaurus 记住。
    colorMode: { respectPrefersColorScheme: true },
    metadata: [{ name: "theme-color", content: "#ffffff" }],
    navbar: {
      title: "Oldman",
      logo: { alt: "", src: "img/logo.svg", width: 24, height: 24 },
      items: [
        { type: "docSidebar", sidebarId: "docs", position: "left", label: "Docs" },
        { type: "docSidebar", sidebarId: "api", position: "left", label: "API" },
        { type: "localeDropdown", position: "right" },
        { href: REPOSITORY, position: "right", className: "navbar-github-link", "aria-label": "GitHub repository" },
      ],
    },
    docs: {
      sidebar: { autoCollapseCategories: false },
    },
    tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 3 },
    footer: {
      style: "light",
      links: [
        {
          title: "Docs",
          items: [
            { label: "User Guide", to: "/docs/users" },
            { label: "Developer Reference", to: "/docs/developers" },
            { label: "Agent Guide", to: "/docs/agents" },
            { label: "API Reference", to: "/docs/api" },
          ],
        },
        {
          title: "Demos",
          items: [
            { label: "EPG dashboard", href: `https://github.com/${ORGANIZATION}/oldman-epg-dashboard` },
            { label: "Built-in Admin", href: `https://github.com/${ORGANIZATION}/oldman-admin-demo` },
            { label: "Ops tool", href: `https://github.com/${ORGANIZATION}/oldman-ops-demo` },
          ],
        },
        {
          title: "Project",
          items: [
            { label: "GitHub", href: REPOSITORY },
            { label: "Releases", href: `${REPOSITORY}/releases` },
            { label: "PyPI", href: "https://pypi.org/project/oldman/" },
            { label: "npm", href: "https://www.npmjs.com/package/oldman-web" },
          ],
        },
      ],
      copyright: "MIT licensed.",
    },
    prism: {
      theme: CODE_LIGHT,
      darkTheme: CODE_DARK,
      additionalLanguages: ["python", "bash", "yaml", "toml", "json", "nginx"],
    },
  },
};
