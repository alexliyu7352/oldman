import { describe, expect, it } from "vitest";
import { compilePoCatalog, createI18n } from "./index";

describe("public i18n exports", () => {
  it("keeps runtime and direct PO parsing on the browser-safe entry", () => {
    const i18n = createI18n({
      locale: "zh-CN",
      messages: {
        Save: "保存"
      }
    });

    const catalog = compilePoCatalog(`
msgid ""
msgstr ""
"Language: zh-CN\\n"

msgid "Open"
msgstr "打开"
`);

    expect(i18n.t("Save")).toBe("保存");
    expect(catalog.messages.Open).toBe("打开");
  });
});
