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
