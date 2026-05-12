#!/usr/bin/env node

import { createInterface } from "node:readline";

import { stringValue, unique } from "./common.mjs";
import { enrichItems } from "./compiler/enrich.mjs";
import { buildProjectGraph } from "./compiler/project-graph.mjs";
import { resolveTypescript } from "./compiler/resolve-typescript.mjs";
import { logger } from "./logging.mjs";

const PROVIDER_NAME = "typescript_semantic_worker";
const STATUS_ONLY = "typescript_worker_status_only";

const main = async () => {
  const lines = createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
  });

  for await (const line of lines) {
    if (!line.trim()) {
      continue;
    }
    try {
      const request = JSON.parse(line);
      logger.debug("request_received", {
        request_id: stringValue(request.request_id),
        item_count: Array.isArray(request.items) ? request.items.length : 0,
      });
      writeResponse(responseFor(request));
    } catch (error) {
      logger.error("request_failed", { error: errorName(error) });
      writeResponse(failedResponse(error));
    }
  }
};

const responseFor = (request) => {
  const mode = stringValue(request.mode) || "auto";
  const repoRoot = stringValue(request.repo_root) || process.cwd();
  const configPath = stringValue(request.config_path);
  const typescript = resolveTypescript(repoRoot);
  const graph = buildProjectGraph({
    repoRoot,
    configPath,
    items: request.items,
    tsModule: typescript.module,
  });
  const typecheckerEnabled = typescript.module !== null && ["project", "required"].includes(mode);
  const caveats = unique([
    ...typescript.caveats,
    ...graph.projectCaveats,
    ...(typecheckerEnabled ? [] : [STATUS_ONLY]),
  ]);
  const items = !typecheckerEnabled
    ? statusItemsFor(request.items, graph.itemOwnership)
    : enrichItems({
        repoRoot,
        items: request.items,
        graph,
        tsModule: typescript.module,
        logger,
      });

  logger.debug("response_ready", {
    request_id: stringValue(request.request_id),
    status: "ready",
    engine: runtimeEngine(),
    engine_version: runtimeEngineVersion(),
    typescript_version: stringValue(typescript.version),
    item_count: items.length,
    caveat_count: caveats.length,
  });

  return {
    request_id: stringValue(request.request_id),
    language: stringValue(request.language) || "TypeScript",
    mode,
    status: "ready",
    provider: {
      name: PROVIDER_NAME,
      mode,
    },
    project: {
      project_cache_key: stringValue(request.project_cache_key),
      config_path: configPath,
      ownership_ambiguous: graph.ownershipAmbiguous,
      caveats,
    },
    items,
    caveats,
  };
};

const statusItemsFor = (items, ownership) => {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.map((item, index) => {
    const owner = ownership[index] ?? {};
    return {
      signature_id: stringValue(item.signature_id),
      resolved: false,
      ownership_ambiguous: owner.ownershipAmbiguous === true,
      caveats: unique([...(owner.caveats ?? []), STATUS_ONLY]),
    };
  });
};

const failedResponse = (error) => {
  return {
    request_id: "",
    language: "TypeScript",
    mode: "auto",
    status: "failed",
    provider: {
      name: PROVIDER_NAME,
      mode: "auto",
    },
    project: {
      caveats: ["typescript_worker_request_failed"],
    },
    items: [],
    caveats: [
      "typescript_worker_request_failed",
      `typescript_worker_error:${errorName(error)}`,
    ],
  };
};

const writeResponse = (response) => {
  process.stdout.write(`${JSON.stringify(response)}\n`);
};

const errorName = (error) => {
  return error && typeof error.name === "string" ? error.name : "Error";
};

const runtimeEngine = () => {
  if (globalThis.Bun) {
    return "bun";
  }
  if (globalThis.Deno) {
    return "deno";
  }
  return "node";
};

const runtimeEngineVersion = () => {
  if (globalThis.Bun?.version) {
    return stringValue(globalThis.Bun.version);
  }
  if (globalThis.Deno?.version?.deno) {
    return stringValue(globalThis.Deno.version.deno);
  }
  return stringValue(process.version);
};

await main();
