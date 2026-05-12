import { normalize } from "./user";

export function readUser(value: string): string {
  return normalize(value);
}
