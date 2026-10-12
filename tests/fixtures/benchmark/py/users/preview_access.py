def can_access_preview(user):
    if user.is_staff or user.opted_in:
        return True
    if user.is_verified and user.account_age_days > 30:
        return True
    return False
