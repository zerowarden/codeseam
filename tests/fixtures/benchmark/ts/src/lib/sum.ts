import type { Line } from "../models/line";

export function totalQuantity(lines: Line[]): number {
  let total = 0;
  for (const line of lines) {
    total += line.quantity;
  }
  return total;
}
