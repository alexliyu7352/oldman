// 文档站配置。内容不在这里，也不属于这里：源是 docs/public/<语言>/，
// scripts/build-docs-site.py 把它组装成 Docusaurus 要的形状后放进暂存树。
// 这个文件是唯一知道 Docusaurus 形状的地方之一，仓库结构不跟着它走。

import { themes } from "prism-react-renderer";

const ORGANIZATION = "alexliyu7352";
const PROJECT = "oldman";
const REPOSITORY = `https://github.com/${ORGANIZATION}/${PROJECT}`;

/** 暂存目录名 -> 源目录名。editUrl 要指回真实的源文件，不是暂存副本。 */
const SOURCE_DIRECTORY = { en: "en", "zh-Hans": "zh" };

export default {
  title: "Oldman",
  tagline: "A batteries-included async Python web framework",
  favicon: "img/favicon.ico",

  url: `https://${ORGANIZATION}.github.io`,
  baseUrl: `/${PROJECT}/`,
  organizationName: ORGANIZATION,
  projectName: PROJECT,

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
          // 纯文档站：文档索引就是首页，不另做一个 React 落地页。
          routeBasePath: "/",
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
    navbar: {
      title: "Oldman",
      items: [
        { type: "docSidebar", sidebarId: "docs", position: "left", label: "Documentation" },
        { type: "localeDropdown", position: "right" },
        { href: REPOSITORY, label: "GitHub", position: "right" },
      ],
    },
    footer: {
      style: "dark",
      copyright: `MIT licensed. Built from <a href="${REPOSITORY}/tree/main/docs/public">docs/public</a>.`,
    },
    prism: {
      theme: themes.github,
      darkTheme: themes.dracula,
      additionalLanguages: ["python", "bash", "yaml", "toml", "json", "nginx"],
    },
  },
};
