import path from "node:path";

export const stringValue = (value) => {
  return typeof value === "string" ? value : "";
};

// TODO: isObject check can be leaner
export const objectValue = (value) => {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
};

export const pathInside = (root, candidate) => {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
};

export const unique = (values) => {
  return Array.from(new Set(values.filter(Boolean)));
};

export const limitText = (value, maxLength = 160) => {
  const text = stringValue(value).replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, Math.max(0, maxLength - 1))}…` : text;
};
