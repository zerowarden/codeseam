import type { AppEvent } from "../models/event";

export function latestEvent(events: AppEvent[]): AppEvent | undefined {
  let pick: AppEvent | undefined;
  for (const event of events) {
    if (event.cancelled) {
      continue;
    }
    if (!pick || event.timestamp > pick.timestamp) {
      pick = event;
    }
  }
  return pick;
}
