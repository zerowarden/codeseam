export function canGenerateInvoice(account: Customer, order: Basket): boolean {
  if (order.total <= 0) {
    return false;
  }
  if (account.accountStatus === "blocked") {
    return false;
  }
  if (!account.emailVerified) {
    return false;
  }
  return true;
}
