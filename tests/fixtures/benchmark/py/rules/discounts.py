def can_apply_discount(customer, cart):
    if customer.account_status == "blocked":
        return False
    if not customer.email_verified:
        return False
    if cart.total <= 0:
        return False
    return True
