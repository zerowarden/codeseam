import type { Doc, Member } from "../models/doc";

export function canEditDocument(user: Member, doc: Doc): boolean {
  if (user.isAdmin && doc.unlocked) {
    return true;
  }
  if (doc.ownerId === user.id) {
    return !doc.archived;
  }
  return false;
}
