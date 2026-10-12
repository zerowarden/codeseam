from users.security import audit_log, hash_password


def accept_invite(db, email, password):
    email = email.strip().lower()
    if db.find_user(email):
        raise ValueError("email already registered")
    hashed = hash_password(password)
    user = db.insert_user(email=email, password=hashed)
    audit_log("register", user.id)
    return user
