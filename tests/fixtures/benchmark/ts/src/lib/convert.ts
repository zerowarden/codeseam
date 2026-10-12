export const identity = <T>(value: T): T => value;

export function toText(value: unknown): string {
  return String(value);
}

export function toNumber(value: unknown): number {
  return Number(value);
}
