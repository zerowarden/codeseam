def can_checkout(user, basket):
    if not user.email_verified:
        return False
    if basket.total <= 0:
        return False
    if user.account_status == "blocked":
        return False
    return True
