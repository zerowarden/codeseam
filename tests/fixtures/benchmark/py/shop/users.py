import json

from shop.models import User


def load_users(path):
    raw = path.read_text()
    data = json.loads(raw)
    return [User.from_dict(item) for item in data["users"]]
