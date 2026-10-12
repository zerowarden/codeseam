from users.security import audit_log, hash_password, send_welcome_email


def register_user(db, email, password):
    email = email.strip().lower()
    if db.find_user(email):
        raise ValueError("email already registered")
    hashed = hash_password(password)
    user = db.insert_user(email=email, password=hashed)
    send_welcome_email(user)
    audit_log("register", user.id)
    return user
