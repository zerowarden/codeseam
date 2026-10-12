def seal_message(cipher, message, key_id):
    key = cipher.load_key(key_id)
    if key is None:
        raise LookupError(key_id)
    payload = message.encode("utf-8")
    result = cipher.encrypt(key, payload)
    return result.hex()
