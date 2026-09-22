import { describe, expect, it } from "vitest";
import { compilePoCatalog, parsePo } from "./po";

describe("parsePo", () => {
  it("parses headers and simple translations", () => {
    const po = `
msgid ""
msgstr ""
"Language: zh-CN\\n"
"Plural-Forms: nplurals=2; plural=n != 1;\\n"

#: src/main.ts:1
msgid "Save"
msgstr "保存"

msgid "Hello, {name}"
msgstr "你好，{name}"
`;

    expect(parsePo(po)).toEqual({
      headers: {
        Language: "zh-CN",
        "Plural-Forms": "nplurals=2; plural=n != 1;"
      },
      entries: [
        {
          msgid: "Save",
          msgstr: "保存"
        },
        {
          msgid: "Hello, {name}",
          msgstr: "你好，{name}"
        }
      ]
    });
  });

  it("parses plural entries", () => {
    const po = `
msgid "{count} file"
msgid_plural "{count} files"
msgstr[0] "{count} fichier"
msgstr[1] "{count} fichiers"
`;

    expect(parsePo(po).entries).toEqual([
      {
        msgid: "{count} file",
        msgidPlural: "{count} files",
        msgstr: ["{count} fichier", "{count} fichiers"]
      }
    ]);
  });

  it("preserves sparse plural indexes and fills empty forms from source", () => {
    const po = `
msgid "{count} file"
msgid_plural "{count} files"
msgstr[0] ""
msgstr[2] "{count} fichiers"
`;

    expect(parsePo(po).entries).toEqual([
      {
        msgid: "{count} file",
        msgidPlural: "{count} files",
        msgstr: [
          "{count} file",
          "{count} files",
          "{count} fichiers"
        ]
      }
    ]);
  });

  it("fills every empty plural form without dropping its index", () => {
    const po = `
msgctxt "upload"
msgid "{count} file"
msgid_plural "{count} files"
msgstr[0] ""
msgstr[1] ""
`;

    expect(parsePo(po).entries).toEqual([
      {
        msgctxt: "upload",
        msgid: "{count} file",
        msgidPlural: "{count} files",
        msgstr: ["{count} file", "{count} files"]
      }
    ]);
  });

  it("parses context entries", () => {
    const po = `
msgctxt "verb"
msgid "Open"
msgstr "打开"

msgctxt "status"
msgid "Open"
msgstr "开放"

msgctxt "upload"
msgid "{count} file"
msgid_plural "{count} files"
msgstr[0] "{count} 个上传文件"
msgstr[1] "{count} 个上传文件"
`;

    expect(parsePo(po).entries).toEqual([
      {
        msgctxt: "verb",
        msgid: "Open",
        msgstr: "打开"
      },
      {
        msgctxt: "status",
        msgid: "Open",
        msgstr: "开放"
      },
      {
        msgctxt: "upload",
        msgid: "{count} file",
        msgidPlural: "{count} files",
        msgstr: ["{count} 个上传文件", "{count} 个上传文件"]
      }
    ]);
  });

  it("skips fuzzy entries", () => {
    const po = `
#, fuzzy
msgid "Save"
msgstr "Sauver"

msgid "Cancel"
msgstr "Annuler"

#, fuzzy, python-format
msgid "{count} file"
msgid_plural "{count} files"
msgstr[0] "{count} fichier"
msgstr[1] "{count} fichiers"
`;

    expect(parsePo(po).entries).toEqual([
      {
        msgid: "Cancel",
        msgstr: "Annuler"
      }
    ]);
  });
});

describe("compilePoCatalog", () => {
  it("compiles PO content into a TranslationCatalog", () => {
    const catalog = compilePoCatalog(`
msgid ""
msgstr ""
"Language: fr\\n"
"Plural-Forms: nplurals=2; plural=n > 1;\\n"

msgid "Save"
msgstr "Enregistrer"

#, fuzzy
msgid "Delete"
msgstr "Supprimer"

msgid "{count} file"
msgid_plural "{count} files"
msgstr[0] "{count} fichier"
msgstr[1] "{count} fichiers"
`);

    expect(catalog).toEqual({
      locale: "fr",
      pluralRule: "n > 1",
      messages: {
        Save: "Enregistrer",
        "{count} file": ["{count} fichier", "{count} fichiers"]
      }
    });
  });

  it("compiles context entries using gettext context keys", () => {
    const catalog = compilePoCatalog(`
msgid ""
msgstr ""
"Language: zh-CN\\n"

msgctxt "verb"
msgid "Open"
msgstr "打开"

msgctxt "status"
msgid "Open"
msgstr "开放"
`);

    expect(catalog.messages).toEqual({
      "verb\u0004Open": "打开",
      "status\u0004Open": "开放"
    });
  });

  it("compiles context plurals with source fallback forms", () => {
    const catalog = compilePoCatalog(`
msgid ""
msgstr ""
"Language: fr\\n"
"Plural-Forms: nplurals=2; plural=n > 1;\\n"

msgctxt "upload"
msgid "{count} file"
msgid_plural "{count} files"
msgstr[0] ""
msgstr[1] "{count} fichiers envoyes"
`);

    expect(catalog.messages).toEqual({
      "upload\u0004{count} file": [
        "{count} file",
        "{count} fichiers envoyes"
      ]
    });
  });

  it("preserves multiline escapes and omits empty translations", () => {
    const catalog = compilePoCatalog(`
msgid ""
msgstr ""
"Language: fr\\n"

msgid "Greeting"
msgstr ""
"Bonjour, "
"monde"

msgctxt "dialog"
msgid "Quoted"
msgstr "Il a dit \\"bonjour\\""

msgid "Missing"
msgstr ""
`);

    expect(catalog).toEqual({
      locale: "fr",
      messages: {
        Greeting: "Bonjour, monde",
        "dialog\u0004Quoted": 'Il a dit "bonjour"'
      }
    });
  });
});

describe("PO string escapes", () => {
  const TAB = String.fromCharCode(9);
  const VERTICAL_TAB = String.fromCharCode(11);
  const BELL = String.fromCharCode(7);

  it("decodes the C escapes gettext allows, not just the JSON subset", () => {
    // readPoString 原先是 JSON.parse。PO 用的是 C 的转义集合,和 JSON 的不是一套:
    // \v、\a、\xNN 在 PO 里合法,JSON.parse 一律抛 SyntaxError。而且 parseBlock /
    // parsePo / compilePoCatalog 一层都没有 try,一个条目里的 \v 会让整份目录加载失败,
    // 不是跳过这一条。
    const source = [
      String.raw`msgid "tab"`,
      String.raw`msgstr "a\tb"`,
      "",
      String.raw`msgid "vertical"`,
      String.raw`msgstr "a\vb"`,
      "",
      String.raw`msgid "bell"`,
      String.raw`msgstr "a\ab"`,
      "",
      String.raw`msgid "hex"`,
      String.raw`msgstr "a\x41b"`,
      "",
      String.raw`msgid "quote"`,
      String.raw`msgstr "a\"b"`
    ].join("\n");

    const catalog = compilePoCatalog(source);

    expect(catalog.messages["tab"]).toBe(`a${TAB}b`);
    expect(catalog.messages["vertical"]).toBe(`a${VERTICAL_TAB}b`);
    expect(catalog.messages["bell"]).toBe(`a${BELL}b`);
    expect(catalog.messages["hex"]).toBe("aAb");
    expect(catalog.messages["quote"]).toBe(String.raw`a"b`);
  });

  it("a single unparsable entry does not take the whole catalog down", () => {
    const source = [
      String.raw`msgid "good"`,
      String.raw`msgstr "fine"`,
      "",
      String.raw`msgid "bad"`,
      String.raw`msgstr "unterminated`,
      "",
      String.raw`msgid "after"`,
      String.raw`msgstr "still here"`
    ].join("\n");

    const catalog = compilePoCatalog(source);

    expect(catalog.messages["good"]).toBe("fine");
    expect(catalog.messages["after"]).toBe("still here");
  });
});
