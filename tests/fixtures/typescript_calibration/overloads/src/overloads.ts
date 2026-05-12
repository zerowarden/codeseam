export function readValue(value: string): string;
export function readValue(value: number): number;
export function readValue(value: string | number): string | number {
  return value;
}

export function callReadValue(): string {
  return readValue("ready");
}
