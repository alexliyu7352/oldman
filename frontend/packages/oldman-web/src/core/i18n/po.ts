import { contextKey, type TranslationCatalog, type TranslationMessages } from "./i18n";

export interface PoEntry {
  msgctxt?: string;
  msgid: string;
  msgidPlural?: string;
  msgstr: string | string[];
}

export interface ParsedPo {
  headers: Record<string, string>;
  entries: PoEntry[];
}

type PoSection = "msgctxt" | "msgid" | "msgidPlural" | "msgstr" | `msgstr:${number}`;

interface MutablePoEntry {
  fuzzy: boolean;
  msgctxt?: string;
  msgid?: string;
  msgidPlural?: string;
  msgstr?: string;
  pluralMsgstr: Record<number, string>;
}

export function parsePo(content: string): ParsedPo {
  const headers: Record<string, string> = {};
  const entries: PoEntry[] = [];

  for (const block of content.split(/\n\s*\n/)) {
    const parsed = parseBlock(block);
    if (parsed?.fuzzy) continue;
    if (!parsed?.msgid) {
      if (parsed?.msgstr) Object.assign(headers, parseHeaders(parsed.msgstr));
      continue;
    }

    if (Object.keys(parsed.pluralMsgstr).length > 0) {
      const pluralEntry: PoEntry = {
        ...(parsed.msgctxt ? { msgctxt: parsed.msgctxt } : {}),
        msgid: parsed.msgid,
        msgstr: normalizedPluralTranslations(parsed)
      };
      if (parsed.msgidPlural) pluralEntry.msgidPlural = parsed.msgidPlural;
      entries.push(pluralEntry);
      continue;
    }

    if (parsed.msgstr) {
      entries.push({
        ...(parsed.msgctxt ? { msgctxt: parsed.msgctxt } : {}),
        msgid: parsed.msgid,
        msgstr: parsed.msgstr
      });
    }
  }

  return { headers, entries };
}

/**
 * Preserve gettext plural indexes and replace empty forms with source text.
 */
function normalizedPluralTranslations(entry: MutablePoEntry): string[] {
  const indexes = Object.keys(entry.pluralMsgstr).map(Number);
  const highestIndex = Math.max(...indexes);
  const singular = entry.msgid ?? "";
  const plural = entry.msgidPlural || singular;
  return Array.from({ length: highestIndex + 1 }, (_value, index) => {
    const translated = entry.pluralMsgstr[index];
    return translated || (index === 0 ? singular : plural);
  });
}

export function compilePoCatalog(content: string, fallbackLocale = "en"): TranslationCatalog {
  const parsed = parsePo(content);
  const messages: TranslationMessages = {};

  for (const entry of parsed.entries) {
    messages[entry.msgctxt ? contextKey(entry.msgctxt, entry.msgid) : entry.msgid] = entry.msgstr;
  }

  const catalog: TranslationCatalog = {
    locale: parsed.headers.Language || fallbackLocale,
    messages
  };
  const pluralRule = parsePluralRule(parsed.headers["Plural-Forms"]);
  if (pluralRule) catalog.pluralRule = pluralRule;
  return catalog;
}

function parseBlock(block: string): MutablePoEntry | null {
  const entry: MutablePoEntry = { fuzzy: false, pluralMsgstr: {} };
  let currentSection: PoSection | null = null;

  for (const rawLine of block.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    if (line.startsWith("#")) {
      if (line.startsWith("#,") && line.includes("fuzzy")) entry.fuzzy = true;
      continue;
    }

    const section = parseSection(line);
    if (section) {
      currentSection = section.name;
      assignSection(entry, currentSection, section.value);
      continue;
    }

    if (currentSection && line.startsWith('"')) {
      assignSection(entry, currentSection, readPoString(line), true);
    }
  }

  return entry.msgid !== undefined || entry.msgstr !== undefined ? entry : null;
}

function parseSection(line: string): { name: PoSection; value: string } | null {
  let match = /^msgctxt\s+(".*")$/.exec(line);
  if (match?.[1]) return { name: "msgctxt", value: readPoString(match[1]) };

  match = /^msgid\s+(".*")$/.exec(line);
  if (match?.[1]) return { name: "msgid", value: readPoString(match[1]) };

  match = /^msgid_plural\s+(".*")$/.exec(line);
  if (match?.[1]) return { name: "msgidPlural", value: readPoString(match[1]) };

  match = /^msgstr\s+(".*")$/.exec(line);
  if (match?.[1]) return { name: "msgstr", value: readPoString(match[1]) };

  match = /^msgstr\[(\d+)]\s+(".*")$/.exec(line);
  if (match?.[1] && match[2]) return { name: `msgstr:${Number(match[1])}`, value: readPoString(match[2]) };

  return null;
}

function assignSection(entry: MutablePoEntry, section: PoSection, value: string, append = false): void {
  if (section === "msgctxt") entry.msgctxt = append ? `${entry.msgctxt ?? ""}${value}` : value;
  if (section === "msgid") entry.msgid = append ? `${entry.msgid ?? ""}${value}` : value;
  if (section === "msgidPlural") entry.msgidPlural = append ? `${entry.msgidPlural ?? ""}${value}` : value;
  if (section === "msgstr") entry.msgstr = append ? `${entry.msgstr ?? ""}${value}` : value;
  if (section.startsWith("msgstr:")) {
    const index = Number(section.slice("msgstr:".length));
    entry.pluralMsgstr[index] = append ? `${entry.pluralMsgstr[index] ?? ""}${value}` : value;
  }
}

function parseHeaders(headerText: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of headerText.split("\n")) {
    const separator = line.indexOf(":");
    if (separator <= 0) continue;
    headers[line.slice(0, separator)] = line.slice(separator + 1).trim();
  }
  return headers;
}

function parsePluralRule(header: string | undefined): string | undefined {
  const match = /plural\s*=\s*([^;]+)/.exec(header ?? "");
  return match?.[1]?.trim();
}

const PO_ESCAPES: Record<string, string> = {
  a: "\u0007",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
  v: "\u000b",
  "\\": "\\",
  '"': '"',
  "'": "'",
  "?": "?"
};

/**
 * 读取一个 PO 字符串字面量（含外层引号）。
 *
 * 不能用 `JSON.parse`：PO 用的是 C 的转义集合，和 JSON 的不是一套。`\v`、`\a`、`\xNN`
 * 在 PO 里合法，`JSON.parse` 一律抛 SyntaxError——而 `parseBlock` / `parsePo` /
 * `compilePoCatalog` 一层都没有 try，所以一个条目里的 `\v` 会让**整份目录**加载失败，
 * 不是跳过这一条。
 *
 * 未知的转义按 gettext 的宽容做法原样保留反斜杠后面的字符。
 */
function readPoString(input: string): string {
  const body = input.slice(1, -1);
  let result = "";
  for (let index = 0; index < body.length; index += 1) {
    const character = body[index]!;
    if (character !== "\\") {
      result += character;
      continue;
    }

    const next = body[index + 1];
    if (next === undefined) break;

    if (next === "x" || next === "X") {
      const hex = /^[0-9a-fA-F]{1,2}/.exec(body.slice(index + 2))?.[0];
      if (hex) {
        result += String.fromCharCode(Number.parseInt(hex, 16));
        index += 1 + hex.length;
        continue;
      }
    }

    const octal = /^[0-7]{1,3}/.exec(body.slice(index + 1))?.[0];
    if (octal) {
      result += String.fromCharCode(Number.parseInt(octal, 8));
      index += octal.length;
      continue;
    }

    result += PO_ESCAPES[next] ?? next;
    index += 1;
  }
  return result;
}
