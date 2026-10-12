import { existsSync, readFileSync } from "node:fs";

export function runImport(job: Job, store: Store): number {
  const source = job.path;
  if (!existsSync(source)) {
    throw new Error(`missing ${source}`);
  }
  const settings = JSON.parse(job.settings || "{}");
  const batchSize = Number(settings.batchSize ?? 100);
  if (batchSize <= 0) {
    throw new Error(`batch size must be positive: ${batchSize}`);
  }
  console.info(`starting ${job.name} with batch size ${batchSize}`);
  let rows: string[][] = [];
  for (const line of readFileSync(source, "utf8").split("\n")) {
    if (!line.trim()) {
      continue;
    }
    rows.push(line.split(","));
    if (rows.length >= batchSize) {
      store.insertMany(rows);
      rows = [];
    }
  }
  if (rows.length) {
    store.insertMany(rows);
  }
  return store.count();
}
