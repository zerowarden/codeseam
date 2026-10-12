import { log } from "./sink";

export const logger = {
  debug: (event: string, fields: object) => log("debug", event, fields),
  info: (event: string, fields: object) => log("info", event, fields),
  warn: (event: string, fields: object) => log("warn", event, fields),
};
