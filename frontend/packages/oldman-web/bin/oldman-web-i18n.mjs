#!/usr/bin/env node
import { resolve, relative, sep, isAbsolute } from "node:path";
import { realpath, readFile, readdir } from "node:fs/promises";
import ts from "typescript";
const CONTEXT_SEPARATOR = "";
function contextKey(context, message) {
  return `${context}${CONTEXT_SEPARATOR}${message}`;
}
function parsePo(content) {
  const headers = {};
  const entries = [];
  for (const block of content.split(/\n\s*\n/)) {
    const parsed = parseBlock(block);
    if (parsed?.fuzzy) continue;
    if (!parsed?.msgid) {
      if (parsed?.msgstr) Object.assign(headers, parseHeaders(parsed.msgstr));
      continue;
    }
    if (Object.keys(parsed.pluralMsgstr).length > 0) {
      const pluralEntry = {
        ...parsed.msgctxt ? { msgctxt: parsed.msgctxt } : {},
        msgid: parsed.msgid,
        msgstr: normalizedPluralTranslations(parsed)
      };
      if (parsed.msgidPlural) pluralEntry.msgidPlural = parsed.msgidPlural;
      entries.push(pluralEntry);
      continue;
    }
    if (parsed.msgstr) {
      entries.push({
        ...parsed.msgctxt ? { msgctxt: parsed.msgctxt } : {},
        msgid: parsed.msgid,
        msgstr: parsed.msgstr
      });
    }
  }
  return { headers, entries };
}
function normalizedPluralTranslations(entry) {
  const indexes = Object.keys(entry.pluralMsgstr).map(Number);
  const highestIndex = Math.max(...indexes);
  const singular = entry.msgid ?? "";
  const plural = entry.msgidPlural || singular;
  return Array.from({ length: highestIndex + 1 }, (_value, index) => {
    const translated = entry.pluralMsgstr[index];
    return translated || (index === 0 ? singular : plural);
  });
}
function compilePoCatalog(content, fallbackLocale = "en") {
  const parsed = parsePo(content);
  const messages = {};
  for (const entry of parsed.entries) {
    messages[entry.msgctxt ? contextKey(entry.msgctxt, entry.msgid) : entry.msgid] = entry.msgstr;
  }
  const catalog = {
    locale: parsed.headers.Language || fallbackLocale,
    messages
  };
  const pluralRule = parsePluralRule(parsed.headers["Plural-Forms"]);
  if (pluralRule) catalog.pluralRule = pluralRule;
  return catalog;
}
function parseBlock(block) {
  const entry = { fuzzy: false, pluralMsgstr: {} };
  let currentSection = null;
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
  return entry.msgid !== void 0 || entry.msgstr !== void 0 ? entry : null;
}
function parseSection(line) {
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
function assignSection(entry, section, value, append = false) {
  if (section === "msgctxt") entry.msgctxt = append ? `${entry.msgctxt ?? ""}${value}` : value;
  if (section === "msgid") entry.msgid = append ? `${entry.msgid ?? ""}${value}` : value;
  if (section === "msgidPlural") entry.msgidPlural = append ? `${entry.msgidPlural ?? ""}${value}` : value;
  if (section === "msgstr") entry.msgstr = append ? `${entry.msgstr ?? ""}${value}` : value;
  if (section.startsWith("msgstr:")) {
    const index = Number(section.slice("msgstr:".length));
    entry.pluralMsgstr[index] = append ? `${entry.pluralMsgstr[index] ?? ""}${value}` : value;
  }
}
function parseHeaders(headerText) {
  const headers = {};
  for (const line of headerText.split("\n")) {
    const separator = line.indexOf(":");
    if (separator <= 0) continue;
    headers[line.slice(0, separator)] = line.slice(separator + 1).trim();
  }
  return headers;
}
function parsePluralRule(header) {
  const match = /plural\s*=\s*([^;]+)/.exec(header ?? "");
  return match?.[1]?.trim();
}
function readPoString(input) {
  return JSON.parse(input);
}
const sourceExtensions = /* @__PURE__ */ new Set([".js", ".jsx", ".ts", ".tsx"]);
const ignoredDirectoryNames = /* @__PURE__ */ new Set([
  "__tests__",
  "dist",
  "fixtures",
  "node_modules",
  "test",
  "tests"
]);
const messageArgumentIndexes = {
  t: [0],
  tc: [0, 1],
  tn: [0, 1],
  tnc: [0, 1, 2]
};
async function extractMessageManifest(sourceRoots, projectRoot) {
  const resolvedProjectRoot = await realpath(resolve(projectRoot));
  const resolvedSourceRoots = [];
  for (const sourceRoot of sourceRoots) {
    const requestedSourceRoot = resolve(sourceRoot);
    let resolvedSourceRoot;
    try {
      resolvedSourceRoot = await realpath(requestedSourceRoot);
    } catch (error) {
      if (error?.code === "ENOENT" || error?.code === "ENOTDIR") {
        throw new Error(
          `frontend source directory does not exist: ${requestedSourceRoot}`
        );
      }
      throw error;
    }
    sourceRootPath(resolvedSourceRoot, resolvedProjectRoot);
    resolvedSourceRoots.push(resolvedSourceRoot);
  }
  const messages = /* @__PURE__ */ new Map();
  for (const sourceRoot of resolvedSourceRoots) {
    for (const filePath of await productionSourceFiles(sourceRoot)) {
      const content = await readFile(filePath, "utf8");
      const sourceFile = parseSourceFile(filePath, content, resolvedProjectRoot);
      collectMessages(
        sourceFile,
        filePath,
        resolvedProjectRoot,
        messages
      );
    }
  }
  return {
    version: 1,
    sources: resolvedSourceRoots.map((sourceRoot) => sourceRootPath(sourceRoot, resolvedProjectRoot)).sort(compareText),
    messages: [...messages.values()].map((message) => ({
      ...message,
      locations: message.locations.sort(compareLocations)
    })).sort(compareMessages)
  };
}
function sourceRootPath(sourceRoot, projectRoot) {
  if (!relative(projectRoot, sourceRoot)) return ".";
  return repositoryPath(sourceRoot, projectRoot);
}
function repositoryPath(filePath, projectRoot) {
  const relativePath = relative(projectRoot, filePath);
  if (!relativePath || relativePath === ".." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
    throw new Error(`${filePath} must be inside project root ${projectRoot}`);
  }
  return relativePath.split(sep).join("/");
}
async function productionSourceFiles(directory) {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "ENOTDIR") {
      throw new Error(`frontend source directory does not exist: ${directory}`);
    }
    throw error;
  }
  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory()) {
      if (!ignoredDirectoryNames.has(entry.name.toLowerCase())) {
        files.push(
          ...await productionSourceFiles(resolve(directory, entry.name))
        );
      }
      continue;
    }
    if (!entry.isFile() || isTestSource(entry.name)) continue;
    if (sourceExtensions.has(extension(entry.name))) {
      files.push(resolve(directory, entry.name));
    }
  }
  return files.sort(compareText);
}
function parseSourceFile(filePath, content, projectRoot) {
  const sourceFile = ts.createSourceFile(
    filePath,
    content,
    ts.ScriptTarget.Latest,
    true,
    scriptKindFor(filePath)
  );
  const diagnostics = sourceFile.parseDiagnostics ?? [];
  if (diagnostics.length > 0) {
    const diagnostic = diagnostics[0];
    const start = diagnostic.start ?? 0;
    const position = sourceFile.getLineAndCharacterOfPosition(start);
    const message = ts.flattenDiagnosticMessageText(
      diagnostic.messageText,
      "\n"
    );
    throw new Error(
      `${repositoryPath(filePath, projectRoot)}:${position.line + 1}:${position.character + 1}: ${message}`
    );
  }
  return sourceFile;
}
function collectMessages(sourceFile, filePath, projectRoot, messages) {
  function visit(node) {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const method = node.expression.name.text;
      if (Object.hasOwn(messageArgumentIndexes, method) && isI18nReceiver(node.expression.expression)) {
        addCallMessage(
          node,
          method,
          sourceFile,
          filePath,
          projectRoot,
          messages
        );
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
}
function isI18nReceiver(expression) {
  if (ts.isIdentifier(expression)) return expression.text === "i18n";
  return ts.isPropertyAccessExpression(expression) && expression.name.text === "i18n";
}
function addCallMessage(call, method, sourceFile, filePath, projectRoot, messages) {
  const requiredIndexes = messageArgumentIndexes[method];
  const values = requiredIndexes.map(
    (argumentIndex) => staticMessageArgument(
      call.arguments[argumentIndex],
      call,
      method,
      argumentIndex,
      sourceFile,
      filePath,
      projectRoot
    )
  );
  const [context, id, plural] = method === "t" ? [null, values[0], null] : method === "tc" ? [values[0], values[1], null] : method === "tn" ? [null, values[0], values[1]] : [values[0], values[1], values[2]];
  const location = sourceFile.getLineAndCharacterOfPosition(
    call.getStart(sourceFile)
  );
  const key = JSON.stringify([context, id]);
  const existing = messages.get(key);
  const sourceLocation = {
    path: repositoryPath(filePath, projectRoot),
    line: location.line + 1
  };
  if (existing) {
    if (existing.plural && plural && existing.plural !== plural) {
      throw sourceError(
        `message ${JSON.stringify(id)} has conflicting plural forms`,
        call,
        sourceFile,
        filePath,
        projectRoot
      );
    }
    if (!existing.plural && plural) existing.plural = plural;
    if (!existing.locations.some(
      (item) => item.path === sourceLocation.path && item.line === sourceLocation.line
    )) {
      existing.locations.push(sourceLocation);
    }
    return;
  }
  messages.set(key, {
    id,
    context,
    plural,
    locations: [sourceLocation]
  });
}
function staticMessageArgument(argument, call, method, argumentIndex, sourceFile, filePath, projectRoot) {
  if (argument && (ts.isStringLiteral(argument) || ts.isNoSubstitutionTemplateLiteral(argument))) {
    if (!argument.text.trim()) {
      throw sourceError(
        "message identity must not be blank",
        argument,
        sourceFile,
        filePath,
        projectRoot
      );
    }
    return argument.text;
  }
  throw sourceError(
    `${method} argument ${argumentIndex + 1} must be a static string literal`,
    argument ?? call,
    sourceFile,
    filePath,
    projectRoot
  );
}
function sourceError(message, node, sourceFile, filePath, projectRoot) {
  const position = sourceFile.getLineAndCharacterOfPosition(
    node.getStart(sourceFile)
  );
  return new Error(
    `${repositoryPath(filePath, projectRoot)}:${position.line + 1}:${position.character + 1}: ${message}`
  );
}
function scriptKindFor(filePath) {
  const fileExtension = extension(filePath);
  if (fileExtension === ".js") return ts.ScriptKind.JS;
  if (fileExtension === ".jsx") return ts.ScriptKind.JSX;
  if (fileExtension === ".tsx") return ts.ScriptKind.TSX;
  return ts.ScriptKind.TS;
}
function extension(filePath) {
  const dot = filePath.lastIndexOf(".");
  return dot < 0 ? "" : filePath.slice(dot).toLowerCase();
}
function isTestSource(fileName) {
  return /\.(?:test|spec)\.(?:[cm]?[jt]sx?)$/i.test(fileName);
}
function compareLocations(left, right) {
  return compareText(left.path, right.path) || left.line - right.line;
}
function compareMessages(left, right) {
  return compareText(left.context ?? "", right.context ?? "") || compareText(left.id, right.id) || compareText(left.plural ?? "", right.plural ?? "");
}
function compareText(left, right) {
  const leftCodePoints = [...left].map(
    (character) => character.codePointAt(0)
  );
  const rightCodePoints = [...right].map(
    (character) => character.codePointAt(0)
  );
  const length = Math.min(leftCodePoints.length, rightCodePoints.length);
  for (let index = 0; index < length; index += 1) {
    const difference = leftCodePoints[index] - rightCodePoints[index];
    if (difference) return difference;
  }
  return leftCodePoints.length - rightCodePoints.length;
}
await main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`${message}
`);
  process.exitCode = 1;
});
async function main() {
  const [command, ...argumentsList] = process.argv.slice(2);
  if (command === "compile-po") {
    await compilePo(argumentsList);
    return;
  }
  if (command === "extract") {
    await extractMessages(argumentsList);
    return;
  }
  throw new Error(
    "Usage: oldman-web-i18n <compile-po|extract> [options]"
  );
}
async function compilePo(argumentsList) {
  let fallbackLocale = "en";
  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument !== "--fallback-locale") {
      throw new Error(`Unknown compile-po argument: ${argument}`);
    }
    const value = argumentsList[index + 1];
    if (!value) throw new Error("--fallback-locale requires a value");
    fallbackLocale = value;
    index += 1;
  }
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const content = Buffer.concat(chunks).toString("utf8");
  const catalog = compilePoCatalog(content, fallbackLocale);
  process.stdout.write(`${JSON.stringify(catalog)}
`);
}
async function extractMessages(argumentsList) {
  let projectRoot = "";
  const sourceRoots = [];
  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument !== "--project-root" && argument !== "--source-root") {
      throw new Error(`Unknown extract argument: ${argument}`);
    }
    const value = argumentsList[index + 1];
    if (!value) throw new Error(`${argument} requires a path`);
    index += 1;
    if (argument === "--project-root") {
      if (projectRoot) {
        throw new Error("--project-root may only be specified once");
      }
      projectRoot = resolve(value);
    } else {
      sourceRoots.push(resolve(value));
    }
  }
  if (!projectRoot) throw new Error("extract requires --project-root");
  if (sourceRoots.length === 0) {
    throw new Error("extract requires at least one --source-root");
  }
  const manifest = await extractMessageManifest(sourceRoots, projectRoot);
  process.stdout.write(`${JSON.stringify(manifest)}
`);
}
