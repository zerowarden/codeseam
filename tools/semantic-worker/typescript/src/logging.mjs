import { objectValue, stringValue } from "./common.mjs";

const LEVELS = new Map([
  ["debug", 10],
  ["info", 20],
  ["warn", 30],
  ["error", 40],
  ["silent", 50],
]);

const COMPONENT = "codeseam.typescript_worker";

const configuredLevel = () => {
  const value = stringValue(process.env.CODESEAM_SEMANTIC_WORKER_LOG).toLowerCase();
  return LEVELS.has(value) ? value : "warn";
};

const enabled = (level) => {
  return (LEVELS.get(level) ?? LEVELS.get("warn")) >= (LEVELS.get(configuredLevel()) ?? 30);
};

const sanitizedFields = (fields) => {
  const output = {};
  for (const [key, value] of Object.entries(objectValue(fields))) {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      output[key] = value;
    } else if (Array.isArray(value)) {
      output[key] = value.filter((item) => typeof item === "string").slice(0, 12);
    }
  }
  return output;
};

export const log = (level, event, fields = {}) => {
  if (!enabled(level)) {
    return;
  }
  process.stderr.write(
    `${JSON.stringify({
      component: COMPONENT,
      level,
      event,
      ...sanitizedFields(fields),
    })}\n`,
  );
};

export const logger = {
  debug: (event, fields) => log("debug", event, fields),
  info: (event, fields) => log("info", event, fields),
  warn: (event, fields) => log("warn", event, fields),
  error: (event, fields) => log("error", event, fields),
};
