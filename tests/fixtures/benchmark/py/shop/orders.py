import json

from shop.models import Order


def get_orders(source):
    text = source.read_text()
    payload = json.loads(text)
    return [Order.from_dict(order) for order in payload["orders"]]
