import type { Line } from "../models/line";

export function cartItemCount(entries: Line[]): number {
  return entries.reduce((acc, entry) => acc + entry.quantity, 0);
}
