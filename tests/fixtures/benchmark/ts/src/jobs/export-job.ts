import { existsSync, writeFileSync } from "node:fs";

export function runExport(job: Job, store: Store): number {
  const target = job.path;
  if (!existsSync(target)) {
    throw new Error(`missing ${target}`);
  }
  const settings = JSON.parse(job.settings || "{}");
  const batchSize = Number(settings.batchSize ?? 500);
  if (batchSize <= 0) {
    throw new Error(`batch size must be positive: ${batchSize}`);
  }
  console.info(`starting ${job.name} with batch size ${batchSize}`);
  let written = 0;
  const lines: string[] = [];
  for (const page of store.pages(batchSize)) {
    lines.push(page.map((row) => row.join(",")).join("\n"));
    written += page.length;
  }
  writeFileSync(target, lines.join("\n"));
  console.info(`exported ${written} rows`);
  return written;
}
