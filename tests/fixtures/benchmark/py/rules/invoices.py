def can_generate_invoice(account, order):
    if order.total <= 0:
        return False
    if account.account_status == "blocked":
        return False
    if not account.email_verified:
        return False
    return True
