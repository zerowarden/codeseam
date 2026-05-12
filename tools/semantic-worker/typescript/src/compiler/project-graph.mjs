import { existsSync } from "node:fs";
import path from "node:path";

import { objectValue, pathInside, stringValue, unique } from "../common.mjs";
import { loadConfig, normalizePath } from "./config.mjs";

const TS_EXTENSIONS = new Set([".ts", ".tsx", ".mts", ".cts"]);
const JS_EXTENSIONS = new Set([".js", ".jsx", ".mjs", ".cjs"]);
const DEFAULT_EXCLUDED_DIRS = new Set(["node_modules", "bower_components", "jspm_packages"]);

export const buildProjectGraph = ({ repoRoot, configPath, items, tsModule }) => {
  const itemList = Array.isArray(items) ? items : [];
  const discovered = discoverProjectConfigs(repoRoot, configPath, itemList);
  const projects = loadProjects(discovered, tsModule);
  const rootProject = projects.get(normalizePath(configPath));
  const itemOwnership = itemList.map((item) => ownershipForItem(repoRoot, item, projects));
  const ownershipAmbiguous = itemOwnership.some((item) => item.ownershipAmbiguous);
  const projectCaveats = [
    ...(rootProject?.caveats ?? ["tsconfig_missing"]),
    ...unique(itemOwnership.flatMap((item) => item.projectCaveats)),
  ];

  return {
    rootProject,
    projects,
    itemOwnership,
    ownershipAmbiguous,
    projectCaveats,
  };
};

const discoverProjectConfigs = (repoRoot, configPath, items) => {
  const configs = new Set();
  const queue = [];
  addConfig(configs, queue, configPath);
  for (const item of items) {
    addConfig(configs, queue, nearestConfig(repoRoot, item));
  }
  return { configs, queue };
};

const loadProjects = (discovered, tsModule) => {
  const projects = new Map();
  while (discovered.queue.length) {
    const configPath = discovered.queue.shift();
    if (projects.has(configPath)) {
      continue;
    }
    const project = loadConfig(configPath, tsModule);
    projects.set(configPath, project);
    for (const reference of project.references) {
      addConfig(discovered.configs, discovered.queue, reference);
    }
  }
  return projects;
};

const ownershipForItem = (repoRoot, item, projects) => {
  const itemPath = itemPathFromRequest(repoRoot, item);
  const owners = [];
  const caveats = [];
  for (const project of projects.values()) {
    if (project.ok && projectOwnsFile(project, itemPath)) {
      owners.push(project);
    }
  }
  if (!owners.length) {
    caveats.push("typescript_project_ownership_missing");
    return {
      signatureId: stringValue(item.signature_id),
      projectConfigPath: "",
      ownershipAmbiguous: false,
      caveats,
      projectCaveats: caveats,
    };
  }
  owners.sort((left, right) => nearestFirst(left, right, itemPath));
  const ownershipAmbiguous = owners.length > 1;
  if (ownershipAmbiguous) {
    caveats.push("typescript_project_ownership_ambiguous");
  }
  return {
    signatureId: stringValue(item.signature_id),
    projectConfigPath: owners[0].path,
    ownershipAmbiguous,
    caveats,
    projectCaveats: caveats,
  };
};

const projectOwnsFile = (project, itemPath) => {
  if (!pathInside(project.dir, itemPath)) {
    return false;
  }
  if (!supportedByProject(project, itemPath)) {
    return false;
  }
  const relpath = relativePath(project.dir, itemPath);
  if (excluded(project, relpath)) {
    return false;
  }
  if (Array.isArray(project.config.files)) {
    return project.config.files.some((entry) => normalizeRelpath(entry) === relpath);
  }
  if (Array.isArray(project.config.include)) {
    return project.config.include.some((pattern) => patternMatches(pattern, relpath));
  }
  return true;
};

const supportedByProject = (project, itemPath) => {
  const extension = path.extname(itemPath);
  if (TS_EXTENSIONS.has(extension)) {
    return true;
  }
  if (!JS_EXTENSIONS.has(extension)) {
    return false;
  }
  const options = objectValue(project.config.compilerOptions);
  return options.allowJs === true || options.checkJs === true;
};

const excluded = (project, relpath) => {
  const compilerOptions = objectValue(project.config.compilerOptions);
  const explicit = Array.isArray(project.config.exclude)
    ? project.config.exclude
    : Array.from(DEFAULT_EXCLUDED_DIRS);
  const generated = [compilerOptions.outDir, compilerOptions.declarationDir].filter(Boolean);
  return [...explicit, ...generated].some((pattern) => patternMatches(pattern, relpath));
};

const patternMatches = (pattern, relpath) => {
  const normalized = normalizeRelpath(pattern);
  if (!normalized) {
    return false;
  }
  if (!hasGlob(normalized)) {
    return path.extname(normalized)
      ? relpath === normalized
      : relpath === normalized || relpath.startsWith(`${normalized}/`);
  }
  return globRegex(normalized).test(relpath);
};

const globRegex = (pattern) => {
  let source = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    const next = pattern[index + 1];
    const afterNext = pattern[index + 2];
    if (char === "*" && next === "*" && afterNext === "/") {
      source += "(?:.*/)?";
      index += 2;
    } else if (char === "*" && next === "*") {
      source += ".*";
      index += 1;
    } else if (char === "*") {
      source += "[^/]*";
    } else if (char === "?") {
      source += "[^/]";
    } else {
      source += escapeRegex(char);
    }
  }
  return new RegExp(`^${source}$`);
};

const nearestConfig = (repoRoot, item) => {
  let current = path.dirname(itemPathFromRequest(repoRoot, item));
  const root = normalizePath(repoRoot);
  while (pathInside(root, current) || current === root) {
    const candidate = path.join(current, "tsconfig.json");
    if (existsSync(candidate)) {
      return normalizePath(candidate);
    }
    const parent = path.dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }
  return "";
};

const addConfig = (configs, queue, configPath) => {
  if (!configPath) {
    return;
  }
  const normalized = normalizePath(configPath);
  if (configs.has(normalized)) {
    return;
  }
  configs.add(normalized);
  queue.push(normalized);
};

const nearestFirst = (left, right, itemPath) => {
  const leftDistance = pathDistance(left.dir, itemPath);
  const rightDistance = pathDistance(right.dir, itemPath);
  return leftDistance - rightDistance || left.path.localeCompare(right.path);
};

const pathDistance = (ownerDir, itemPath) => {
  return relativePath(ownerDir, itemPath).split("/").length;
};

export const itemPathFromRequest = (repoRoot, item) => {
  const relative = stringValue(item.relative_path);
  return normalizePath(path.resolve(repoRoot, relative));
};

export const relativePath = (root, candidate) => {
  return normalizeRelpath(path.relative(root, candidate));
};

const normalizeRelpath = (value) => {
  return stringValue(value).replaceAll("\\", "/").replace(/^\.\//, "");
};

const hasGlob = (value) => {
  return value.includes("*") || value.includes("?");
};

const escapeRegex = (char) => {
  return /[\\^$+?.()|[\]{}]/.test(char) ? `\\${char}` : char;
};
