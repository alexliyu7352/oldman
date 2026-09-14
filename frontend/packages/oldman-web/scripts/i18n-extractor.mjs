import { readFile, readdir, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";

import ts from "typescript";

const sourceExtensions = new Set([".js", ".jsx", ".ts", ".tsx"]);
const ignoredDirectoryNames = new Set([
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

/**
 * Scan production source roots and return the canonical frontend message manifest.
 */
export async function extractMessageManifest(sourceRoots, projectRoot) {
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
  const messages = new Map();
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
    sources: resolvedSourceRoots
      .map((sourceRoot) => sourceRootPath(sourceRoot, resolvedProjectRoot))
      .sort(compareText),
    messages: [...messages.values()]
      .map((message) => ({
        ...message,
        locations: message.locations.sort(compareLocations)
      }))
      .sort(compareMessages)
  };
}

/**
 * Normalize a source root while allowing the project root itself.
 */
function sourceRootPath(sourceRoot, projectRoot) {
  if (!relative(projectRoot, sourceRoot)) return ".";
  return repositoryPath(sourceRoot, projectRoot);
}

/**
 * Normalize an absolute path to a project-relative POSIX path.
 */
export function repositoryPath(filePath, projectRoot) {
  const relativePath = relative(projectRoot, filePath);
  if (
    !relativePath
    || relativePath === ".."
    || relativePath.startsWith(`..${sep}`)
    || isAbsolute(relativePath)
  ) {
    throw new Error(`${filePath} must be inside project root ${projectRoot}`);
  }
  return relativePath.split(sep).join("/");
}

/**
 * Recursively enumerate only production JavaScript and TypeScript sources.
 */
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
          ...(await productionSourceFiles(resolve(directory, entry.name)))
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

/**
 * Parse one source file and reject syntax errors before message traversal.
 */
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

/**
 * Visit one source AST and collect static calls to I18nRuntime methods.
 */
function collectMessages(
  sourceFile,
  filePath,
  projectRoot,
  messages
) {
  function visit(node) {
    if (
      ts.isCallExpression(node)
      && ts.isPropertyAccessExpression(node.expression)
    ) {
      const method = node.expression.name.text;
      if (
        Object.hasOwn(messageArgumentIndexes, method)
        && isI18nReceiver(node.expression.expression)
      ) {
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

/**
 * Limit extraction to calls made through an object named ``i18n``.
 */
function isI18nReceiver(expression) {
  if (ts.isIdentifier(expression)) return expression.text === "i18n";
  return (
    ts.isPropertyAccessExpression(expression)
    && expression.name.text === "i18n"
  );
}

/**
 * Convert one t/tc/tn/tnc call into the canonical manifest shape.
 */
function addCallMessage(
  call,
  method,
  sourceFile,
  filePath,
  projectRoot,
  messages
) {
  const requiredIndexes = messageArgumentIndexes[method];
  const values = requiredIndexes.map((argumentIndex) =>
    staticMessageArgument(
      call.arguments[argumentIndex],
      call,
      method,
      argumentIndex,
      sourceFile,
      filePath,
      projectRoot
    )
  );
  const [context, id, plural] =
    method === "t"
      ? [null, values[0], null]
      : method === "tc"
        ? [values[0], values[1], null]
        : method === "tn"
          ? [null, values[0], values[1]]
          : [values[0], values[1], values[2]];
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
    if (
      !existing.locations.some(
        (item) =>
          item.path === sourceLocation.path
          && item.line === sourceLocation.line
      )
    ) {
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

/**
 * Require every message identity argument to be a static string literal.
 */
function staticMessageArgument(
  argument,
  call,
  method,
  argumentIndex,
  sourceFile,
  filePath,
  projectRoot
) {
  if (
    argument
    && (
      ts.isStringLiteral(argument)
      || ts.isNoSubstitutionTemplateLiteral(argument)
    )
  ) {
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

/**
 * Build one deterministic extraction error with a project-relative location.
 */
function sourceError(
  message,
  node,
  sourceFile,
  filePath,
  projectRoot
) {
  const position = sourceFile.getLineAndCharacterOfPosition(
    node.getStart(sourceFile)
  );
  return new Error(
    `${repositoryPath(filePath, projectRoot)}:${position.line + 1}:${position.character + 1}: ${message}`
  );
}

/**
 * Select the TypeScript parser mode for each supported source extension.
 */
function scriptKindFor(filePath) {
  const fileExtension = extension(filePath);
  if (fileExtension === ".js") return ts.ScriptKind.JS;
  if (fileExtension === ".jsx") return ts.ScriptKind.JSX;
  if (fileExtension === ".tsx") return ts.ScriptKind.TSX;
  return ts.ScriptKind.TS;
}

/**
 * Return a lowercase file extension without another runtime dependency.
 */
function extension(filePath) {
  const dot = filePath.lastIndexOf(".");
  return dot < 0 ? "" : filePath.slice(dot).toLowerCase();
}

/**
 * Exclude tests and specs regardless of their JavaScript/TypeScript extension.
 */
function isTestSource(fileName) {
  return /\.(?:test|spec)\.(?:[cm]?[jt]sx?)$/i.test(fileName);
}

/**
 * Keep source locations stable within each unique message.
 */
function compareLocations(left, right) {
  return compareText(left.path, right.path) || left.line - right.line;
}

/**
 * Keep message ordering independent from filesystem traversal order.
 */
function compareMessages(left, right) {
  return (
    compareText(left.context ?? "", right.context ?? "")
    || compareText(left.id, right.id)
    || compareText(left.plural ?? "", right.plural ?? "")
  );
}

/**
 * Compare Unicode code points exactly like Python stable string ordering.
 */
function compareText(left, right) {
  const leftCodePoints = [...left].map((character) =>
    character.codePointAt(0)
  );
  const rightCodePoints = [...right].map((character) =>
    character.codePointAt(0)
  );
  const length = Math.min(leftCodePoints.length, rightCodePoints.length);
  for (let index = 0; index < length; index += 1) {
    const difference = leftCodePoints[index] - rightCodePoints[index];
    if (difference) return difference;
  }
  return leftCodePoints.length - rightCodePoints.length;
}
