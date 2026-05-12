import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { objectValue, stringValue } from "../common.mjs";

export const loadConfig = (configPath, tsModule, seen = new Set()) => {
  if (!configPath) {
    return missingConfig(configPath, "tsconfig_path_missing");
  }
  const resolvedPath = normalizePath(configPath);
  if (!existsSync(resolvedPath)) {
    return missingConfig(resolvedPath, "tsconfig_missing");
  }
  if (seen.has(resolvedPath)) {
    return missingConfig(resolvedPath, "tsconfig_extends_cycle");
  }
  const parsed = readConfig(resolvedPath, tsModule);
  if (!parsed.ok) {
    return missingConfig(resolvedPath, parsed.caveat);
  }

  const nextSeen = new Set(seen);
  nextSeen.add(resolvedPath);
  const extended = extendedConfig(resolvedPath, parsed.config, tsModule, nextSeen);
  const config = mergeConfig(extended.config, parsed.config);
  return {
    ok: true,
    path: resolvedPath,
    dir: path.dirname(resolvedPath),
    config,
    rootFileCount: Array.isArray(config.files) ? config.files.length : 0,
    projectReferenceCount: Array.isArray(config.references) ? config.references.length : 0,
    references: referencedConfigPaths(resolvedPath, config.references),
    caveats: [...parsed.caveats, ...extended.caveats],
  };
};

const readConfig = (configPath, tsModule) => {
  if (tsModule !== null && typeof tsModule.readConfigFile === "function") {
    const result = tsModule.readConfigFile(configPath, tsModule.sys.readFile);
    if (result.error) {
      return { ok: false, caveat: "tsconfig_parse_failed" };
    }
    return { ok: true, config: result.config ?? {}, caveats: [] };
  }
  try {
    return {
      ok: true,
      config: JSON.parse(stripBom(readFileSync(configPath, "utf8"))),
      caveats: ["tsconfig_parsed_without_typescript"],
    };
  } catch {
    return { ok: false, caveat: "tsconfig_parse_failed" };
  }
};

const extendedConfig = (configPath, config, tsModule, seen) => {
  const specifier = stringValue(config.extends);
  if (!specifier) {
    return { config: {}, caveats: [] };
  }
  const extendedPath = resolveExtendsPath(configPath, specifier);
  if (!extendedPath) {
    return { config: {}, caveats: ["tsconfig_extends_unresolved"] };
  }
  const loaded = loadConfig(extendedPath, tsModule, seen);
  if (!loaded.ok) {
    return { config: {}, caveats: loaded.caveats };
  }
  return { config: loaded.config, caveats: loaded.caveats };
};

const resolveExtendsPath = (configPath, specifier) => {
  if (!specifier.startsWith(".") && !path.isAbsolute(specifier)) {
    return "";
  }
  const base = path.resolve(path.dirname(configPath), specifier);
  if (existsSync(base) && statSync(base).isFile()) {
    return normalizePath(base);
  }
  if (existsSync(`${base}.json`)) {
    return normalizePath(`${base}.json`);
  }
  const nested = path.join(base, "tsconfig.json");
  return existsSync(nested) ? normalizePath(nested) : "";
};

const mergeConfig = (base, child) => {
  return {
    ...base,
    ...child,
    compilerOptions: {
      ...(objectValue(base.compilerOptions)),
      ...(objectValue(child.compilerOptions)),
    },
  };
};

const referencedConfigPaths = (configPath, references) => {
  if (!Array.isArray(references)) {
    return [];
  }
  return references
    .map((reference) => referencedConfigPath(configPath, reference))
    .filter((value) => value);
};

const referencedConfigPath = (configPath, reference) => {
  const referencePath = stringValue(reference?.path);
  if (!referencePath) {
    return "";
  }
  const absolute = path.resolve(path.dirname(configPath), referencePath);
  if (existsSync(absolute) && absolute.endsWith(".json") && statSync(absolute).isFile()) {
    return normalizePath(absolute);
  }
  const nested = path.join(absolute, "tsconfig.json");
  return existsSync(nested) ? normalizePath(nested) : "";
};

const missingConfig = (configPath, caveat) => {
  return {
    ok: false,
    path: configPath || "",
    dir: configPath ? path.dirname(configPath) : "",
    config: {},
    rootFileCount: 0,
    projectReferenceCount: 0,
    references: [],
    caveats: [caveat],
  };
};

export const normalizePath = (value) => {
  return path.resolve(value).replaceAll(path.sep, "/");
};

const stripBom = (value) => {
  return value.charCodeAt(0) === 0xfeff ? value.slice(1) : value;
};
