type FindingDraft = { title: string };

export function targetSectionItems(value: unknown): FindingDraft[] {
  return [{ title: String(value) }];
}

export function targetSectionRows(value: unknown): FindingDraft[] {
  return [{ title: String(value).trim() }];
}
