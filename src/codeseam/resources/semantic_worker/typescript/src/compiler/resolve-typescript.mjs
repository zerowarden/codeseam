import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { pathInside, stringValue } from "../common.mjs";

const requireFromWorker = createRequire(import.meta.url);

export const resolveTypescript = (repoRoot) => {
  try {
    const modulePath = requireFromWorker.resolve("typescript", { paths: [repoRoot] });
    const packagePath = requireFromWorker.resolve("typescript/package.json", {
      paths: [repoRoot],
    });
    const packageJson = JSON.parse(readFileSync(packagePath, "utf8"));
    return {
      module: requireFromWorker(modulePath),
      version: stringValue(packageJson.version),
      caveats: [...typescriptResolutionCaveats(repoRoot, packagePath), ...pnpCaveats(repoRoot)],
    };
  } catch {
    return {
      module: null,
      version: "",
      caveats: ["typescript_package_unavailable", ...pnpCaveats(repoRoot)],
    };
  }
};

const typescriptResolutionCaveats = (repoRoot, packagePath) => {
  return pathInside(repoRoot, packagePath) ? [] : ["typescript_package_not_repo_local"];
};

const pnpCaveats = (repoRoot) => {
  return existsSync(path.join(repoRoot, ".pnp.cjs")) || existsSync(path.join(repoRoot, ".pnp.loader.mjs"))
    ? ["typescript_pnp_project_without_loader"]
    : [];
};
