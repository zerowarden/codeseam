export function canCheckout(user: Customer, basket: Basket): boolean {
  if (!user.emailVerified) {
    return false;
  }
  if (basket.total <= 0) {
    return false;
  }
  if (user.accountStatus === "blocked") {
    return false;
  }
  return true;
}
