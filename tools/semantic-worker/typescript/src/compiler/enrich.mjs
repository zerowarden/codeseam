import path from "node:path";

import { limitText, pathInside, stringValue, unique } from "../common.mjs";
import { itemPathFromRequest, relativePath } from "./project-graph.mjs";

const MAX_TYPE_TEXT_CHARS = 160;
const MAX_CALL_TARGETS = 5;

export const enrichItems = ({ repoRoot, items, graph, tsModule, logger }) => {
  const itemList = Array.isArray(items) ? items : [];
  if (tsModule === null) {
    logger.debug("typechecker_unavailable", { item_count: itemList.length });
    return itemList.map((item, index) =>
      unresolvedItem(item, graph.itemOwnership[index], ["typescript_typechecker_unavailable"]),
    );
  }

  const programs = new Map();
  return itemList.map((item, index) => {
    const owner = graph.itemOwnership[index] ?? {};
    if (!stringValue(owner.projectConfigPath)) {
      return unresolvedItem(item, owner);
    }
    try {
      const program = programFor(projectFor(graph, owner.projectConfigPath), tsModule, programs);
      return enrichItem({
        repoRoot,
        item,
        owner,
        program,
        checker: program.getTypeChecker(),
        tsModule,
      });
    } catch (error) {
      logger.warn("item_enrichment_failed", {
        signature_id: stringValue(item.signature_id),
        error: errorName(error),
      });
      return unresolvedItem(item, owner, [`typescript_typechecker_error:${errorName(error)}`]);
    }
  });
};

const programFor = (project, tsModule, programs) => {
  if (!project?.ok) {
    throw new Error("project_unavailable");
  }
  if (programs.has(project.path)) {
    return programs.get(project.path);
  }
  const parsed = parsedProject(project.path, tsModule);
  const program = tsModule.createProgram({
    rootNames: parsed.fileNames,
    options: { ...parsed.options, noEmit: true },
    projectReferences: parsed.projectReferences,
  });
  programs.set(project.path, program);
  return program;
};

const parsedProject = (configPath, tsModule) => {
  const host = {
    ...tsModule.sys,
    onUnRecoverableConfigFileDiagnostic: () => {},
  };
  const parsed = tsModule.getParsedCommandLineOfConfigFile(configPath, { noEmit: true }, host);
  if (!parsed) {
    throw new Error("tsconfig_parse_failed");
  }
  return parsed;
};

const projectFor = (graph, configPath) => {
  return graph.projects.get(configPath);
};

const enrichItem = ({ repoRoot, item, owner, program, checker, tsModule }) => {
  const itemPath = itemPathFromRequest(repoRoot, item);
  const sourceFile = program.getSourceFile(itemPath);
  if (!sourceFile) {
    return unresolvedItem(item, owner, ["typescript_source_file_missing"]);
  }

  const span = sourceSpan(sourceFile, item);
  const node = signatureNodeAtSpan(sourceFile, span, tsModule, stringValue(item.symbol_hint));
  if (!node) {
    return unresolvedItem(item, owner, ["typescript_signature_node_unresolved"]);
  }

  const signature = checker.getSignatureFromDeclaration(node);
  if (!signature) {
    return unresolvedItem(item, owner, ["typescript_signature_unresolved"]);
  }

  const symbol = symbolForNode(node, checker, tsModule);
  const hasBody = Boolean(node.body);
  return {
    signature_id: stringValue(item.signature_id),
    resolved: true,
    ownership_ambiguous: owner.ownershipAmbiguous === true,
    symbol: symbolPayload({ repoRoot, sourceFile, symbol, node }),
    overload_group_id: overloadGroupId({ repoRoot, sourceFile, symbol, node, tsModule }),
    declaration_only: sourceFile.isDeclarationFile || !hasBody,
    return_type: returnType(signature, node, checker, tsModule),
    call_targets: callTargets({ repoRoot, sourceFile, node, checker, tsModule }),
    caveats: unique(owner.caveats ?? []),
  };
};

const unresolvedItem = (item, owner = {}, caveats = []) => {
  return {
    signature_id: stringValue(item.signature_id),
    resolved: false,
    ownership_ambiguous: owner.ownershipAmbiguous === true,
    caveats: unique([...(owner.caveats ?? []), ...caveats]),
  };
};

const sourceSpan = (sourceFile, item) => {
  if (Number.isInteger(item.start_byte) && Number.isInteger(item.end_byte)) {
    return { start: item.start_byte, end: item.end_byte };
  }
  const lineStarts = sourceFile.getLineStarts();
  const startLine = Math.max(1, Number(item.start_line) || 1);
  const endLine = Math.max(startLine, Number(item.end_line) || startLine);
  const start = lineStarts[startLine - 1] ?? 0;
  const nextLineStart = lineStarts[endLine] ?? sourceFile.text.length;
  let end = nextLineStart;
  while (end > start && /\s/.test(sourceFile.text[end - 1] ?? "")) {
    end -= 1;
  }
  return { start, end };
};

const signatureNodeAtSpan = (sourceFile, span, tsModule, symbolHint) => {
  const node = smallestNodeContaining(sourceFile, span, tsModule);
  return nearestSignatureNode(node, tsModule) ?? signatureDescendantInSpan(sourceFile, span, tsModule, symbolHint);
};

const smallestNodeContaining = (sourceFile, span, tsModule) => {
  let best = sourceFile;
  const visit = (node) => {
    const start = node.getStart(sourceFile);
    const end = node.getEnd();
    if (start <= span.start && end >= span.end) {
      best = node;
      tsModule.forEachChild(node, visit);
    }
  };
  visit(sourceFile);
  return best;
};

const nearestSignatureNode = (node, tsModule) => {
  let current = node;
  while (current) {
    if (isSignatureLike(current, tsModule)) {
      return current;
    }
    current = current.parent;
  }
  return null;
};

const signatureDescendantInSpan = (sourceFile, span, tsModule, symbolHint) => {
  const candidates = [];
  const visit = (node) => {
    if (isSignatureLike(node, tsModule) && node.getStart(sourceFile) >= span.start && node.getEnd() <= span.end) {
      candidates.push(node);
    }
    tsModule.forEachChild(node, visit);
  };
  visit(sourceFile);
  return (
    candidates.find((node) => signatureName(node, sourceFile, tsModule) === symbolHint) ??
    candidates.sort((left, right) => nodeWidth(left) - nodeWidth(right))[0] ??
    null
  );
};

const signatureName = (node, sourceFile, tsModule) => {
  return node.name?.getText(sourceFile) ?? variableName(node, tsModule)?.getText(sourceFile) ?? "";
};

const nodeWidth = (node) => {
  return node.getEnd() - node.getStart();
};

const isSignatureLike = (node, tsModule) => {
  return (
    tsModule.isFunctionDeclaration(node) ||
    tsModule.isMethodDeclaration(node) ||
    tsModule.isConstructorDeclaration(node) ||
    tsModule.isGetAccessorDeclaration(node) ||
    tsModule.isSetAccessorDeclaration(node) ||
    tsModule.isFunctionExpression(node) ||
    tsModule.isArrowFunction(node) ||
    tsModule.isFunctionTypeNode(node) ||
    tsModule.isMethodSignature(node) ||
    tsModule.isCallSignatureDeclaration(node) ||
    tsModule.isConstructSignatureDeclaration(node)
  );
};

const symbolForNode = (node, checker, tsModule) => {
  const name = node.name ?? variableName(node, tsModule);
  return name ? checker.getSymbolAtLocation(name) : node.symbol;
};

const variableName = (node, tsModule) => {
  const parent = node.parent;
  if (parent && tsModule.isVariableDeclaration(parent) && parent.name) {
    return parent.name;
  }
  return null;
};

const symbolPayload = ({ repoRoot, sourceFile, symbol, node }) => {
  const declaration = declarationForSymbol(symbol) ?? node;
  return {
    name: symbol?.getName() ?? node.name?.getText(sourceFile) ?? "",
    declaration_file: declarationFile(repoRoot, declaration),
  };
};

const declarationForSymbol = (symbol) => {
  return symbol?.valueDeclaration ?? symbol?.declarations?.[0] ?? null;
};

const declarationFile = (repoRoot, node) => {
  const fileName = node.getSourceFile().fileName;
  return pathInside(repoRoot, fileName) ? relativePath(repoRoot, fileName) : fileName;
};

const overloadGroupId = ({ repoRoot, sourceFile, symbol, node, tsModule }) => {
  if (!symbol || !Array.isArray(symbol.declarations)) {
    return null;
  }
  const signatureDeclarations = symbol.declarations.filter((declaration) =>
    isSignatureLike(declaration, tsModule),
  );
  if (signatureDeclarations.length <= 1) {
    return null;
  }
  const name = symbol.getName() || node.name?.getText(sourceFile) || "";
  return `${declarationFile(repoRoot, signatureDeclarations[0])}::${name}`;
};

const returnType = (signature, node, checker, tsModule) => {
  return typeText(checker.getReturnTypeOfSignature(signature), node, checker, tsModule);
};

const typeText = (type, node, checker, tsModule) => {
  return limitText(checker.typeToString(type, node, typeFormatFlags(tsModule)), MAX_TYPE_TEXT_CHARS);
};

const typeFormatFlags = (tsModule) => {
  return (
    (tsModule.TypeFormatFlags?.NoTruncation ?? 0) |
    (tsModule.TypeFormatFlags?.UseFullyQualifiedType ?? 0)
  );
};

const callTargets = ({ repoRoot, sourceFile, node, checker, tsModule }) => {
  if (!node.body) {
    return [];
  }
  const targets = [];
  const visit = (child) => {
    if (targets.length >= MAX_CALL_TARGETS) {
      return;
    }
    if (tsModule.isCallExpression(child)) {
      targets.push(callTarget({ repoRoot, sourceFile, call: child, checker }));
    }
    tsModule.forEachChild(child, visit);
  };
  tsModule.forEachChild(node.body, visit);
  return targets;
};

const callTarget = ({ repoRoot, sourceFile, call, checker }) => {
  const token = limitText(call.expression.getText(sourceFile), 80);
  const resolved = checker.getResolvedSignature(call);
  const declaration = resolved?.getDeclaration?.() ?? null;
  const symbol = checker.getSymbolAtLocation(call.expression) ?? symbolForDeclaration(declaration, checker);
  return {
    call_token: token,
    resolved: Boolean(resolved),
    symbol_name: symbol?.getName() ?? declaration?.name?.getText(sourceFile) ?? "",
    declaration_file: declaration ? declarationFile(repoRoot, declaration) : "",
    caveats: resolved ? [] : ["typescript_call_unresolved"],
  };
};

const symbolForDeclaration = (declaration, checker) => {
  return declaration?.name ? checker.getSymbolAtLocation(declaration.name) : null;
};

const errorName = (error) => {
  return error && typeof error.name === "string" ? error.name : "Error";
};
