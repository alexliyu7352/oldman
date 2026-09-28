// 侧边栏在构建时算出来，不是一份需要跟着文档一起维护的清单。
//
// 顺序取自每个目录自己的 README：那里本来就是给人看的导览，顺序是它的语义。
// 把顺序写进各篇的 frontmatter 或文件名前缀，等于让几十个文件各记一点排序意图，
// 而且会和 URL、链接目标绑死；从 README 推导则只有一个事实来源，改 README 即生效。
//
// 目录可以任意层嵌套：子目录变成折叠的子分类，标题取它自己 README 的一级标题。
// 上级 README 里指向 `子目录/任意文件.md` 的链接决定子分类排在哪个位置。
//
// 读的是暂存树（scripts/build-docs-site.py 组装的那棵），所以它总是完整的：
// 缺英文译文的那几篇也在里面，侧边栏不会因为翻译进度而少条目。

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STAGED = path.join(HERE, ".staging", "en");

/** 顶层分区的标题。中文标题由 i18n/<locale>/…/current.json 覆盖。 */
const SECTION_LABELS = {
  users: "User Guide",
  developers: "Developer Reference",
  agents: "Agent Guide",
};

/**
 * 从一个 README 里读出它列出的条目，按出现顺序去重。
 *
 * 只认指向本目录或其子目录的相对链接：README 里还有大量指向别的分区的交叉引用，
 * 那些是正文里的导航，不是这个目录的目录树。返回的是「条目名」——一篇文档就是它的
 * 文件名，一个子目录就是目录名。
 */
function orderFromReadme(directory) {
  const readme = path.join(directory, "README.md");
  if (!fs.existsSync(readme)) return [];

  const order = [];
  for (const match of fs.readFileSync(readme, "utf8").matchAll(/\]\(\s*(?:\.\/)?([A-Za-z0-9._\-/]+)\.md[^)]*\)/g)) {
    const target = match[1];
    if (target.startsWith("../")) continue;
    // `子目录/文件` 记子目录，`文件` 记文件本身。
    const entry = target.includes("/") ? target.split("/")[0] : target;
    if (entry !== "README" && !order.includes(entry)) order.push(entry);
  }
  return order;
}

/** 目录的显示名：取它 README 的一级标题，没有就用目录名。 */
function labelOf(directory, name) {
  if (SECTION_LABELS[name]) return SECTION_LABELS[name];
  const readme = path.join(directory, "README.md");
  if (fs.existsSync(readme)) {
    const heading = fs.readFileSync(readme, "utf8").match(/^#\s+(.+)$/m);
    if (heading) return heading[1].trim();
  }
  return name;
}

/**
 * 把一个目录变成侧边栏条目数组。
 *
 * `relative` 是相对暂存树根的路径，也就是 Docusaurus 的文档 id 前缀。
 */
function itemsOf(directory, relative) {
  const entries = fs.readdirSync(directory, { withFileTypes: true });
  const documents = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md") && entry.name !== "README.md")
    .map((entry) => entry.name.slice(0, -3));
  const subdirectories = entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name);

  const present = new Set([...documents, ...subdirectories]);
  const listed = orderFromReadme(directory).filter((name) => present.has(name));
  const unlisted = [...present].filter((name) => !listed.includes(name)).sort();
  if (unlisted.length > 0) {
    // 不是错误：新文档可以先落地再补进导览。但它会排在末尾，所以说出来。
    const where = relative || ".";
    console.warn(`[sidebars] ${where}: ${unlisted.join(", ")} 未出现在 README.md，已排到末尾`);
  }

  return [...listed, ...unlisted].map((name) => {
    const child = path.join(directory, name);
    const childRelative = relative ? `${relative}/${name}` : name;
    if (!subdirectories.includes(name)) return childRelative;
    return {
      type: "category",
      label: labelOf(child, name),
      collapsed: relative !== "",
      // 子目录有 README 就用它当分类首页，点分类标题直接进入。
      ...(fs.existsSync(path.join(child, "README.md"))
        ? { link: { type: "doc", id: `${childRelative}/README` } }
        : {}),
      items: itemsOf(child, childRelative),
    };
  });
}

export default {
  docs: ["README", ...itemsOf(STAGED, "")],
};
