def can_access_beta(user):
    if user.is_staff and user.opted_in:
        return True
    if user.is_verified and user.account_age_days > 30:
        return True
    return False
