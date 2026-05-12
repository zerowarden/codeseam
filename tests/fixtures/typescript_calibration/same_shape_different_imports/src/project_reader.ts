import { normalize } from "./project";

export function readProject(value: string): string {
  return normalize(value);
}
