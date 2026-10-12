import type { Item } from "../models/item";

export function visibleItemIds(items: Item[], section: string): string[] {
  const ids: string[] = [];
  for (const item of items) {
    if (item.section !== section) {
      continue;
    }
    if (item.visible) {
      ids.push(item.id);
    }
  }
  return ids.sort();
}
