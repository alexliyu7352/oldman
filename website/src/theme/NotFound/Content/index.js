// 404 页的内容（从 @docusaurus/theme-classic 弹出）：原文让读者"去联系链接的主人"，对读者没有用；
// 这里说明可能的原因，并给出文档与 API 两个入口。中文译文在 i18n/zh-Hans/code.json。

import Heading from "@theme/Heading";
import Link from "@docusaurus/Link";
import Translate from "@docusaurus/Translate";

export default function NotFoundContent({ className }) {
  return (
    <main className={["container margin-vert--xl", className].filter(Boolean).join(" ")}>
      <div className="row">
        <div className="col col--6 col--offset-3">
          <Heading as="h1">
            <Translate id="notFound.title">Page not found</Translate>
          </Heading>
          <p>
            <Translate id="notFound.text">
              Nothing is published at this address. It may be mistyped, or the page may have moved; the search box at the top looks
              through every page.
            </Translate>
          </p>
          <div className="margin-top--lg" style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
            <Link className="button button--primary" to="/docs">
              <Translate id="notFound.docs">Open the documentation</Translate>
            </Link>
            <Link className="button button--secondary button--outline" to="/docs/api">
              <Translate id="notFound.api">Open the API reference</Translate>
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
