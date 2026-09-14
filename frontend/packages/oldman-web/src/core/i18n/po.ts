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

function readPoString(input: string): string {
  return JSON.parse(input) as string;
}
