import { normalize } from "./shared";

export function readUser(value: string): string {
  return normalize(value);
}

export function readProject(value: string): string {
  return normalize(value);
}
