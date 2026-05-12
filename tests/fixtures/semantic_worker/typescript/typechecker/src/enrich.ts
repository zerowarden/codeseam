export function parseUser(value: string): number {
  return Number(value);
}

export function callParse(): number {
  return parseUser("7");
}

export const isCustomList = (list: HTMLElement): boolean => /\btox-/.test(list.className);

export function pick(value: string): string;
export function pick(value: number): number;
export function pick(value: string | number): string | number {
  return value;
}
