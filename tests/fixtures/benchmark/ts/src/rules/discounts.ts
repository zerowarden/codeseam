export function canApplyDiscount(customer: Customer, cart: Basket): boolean {
  if (customer.accountStatus === "blocked") {
    return false;
  }
  if (!customer.emailVerified) {
    return false;
  }
  if (cart.total <= 0) {
    return false;
  }
  return true;
}
