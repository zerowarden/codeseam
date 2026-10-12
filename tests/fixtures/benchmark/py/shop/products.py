import json

from shop.models import Product


def read_products(file_path):
    contents = file_path.read_text()
    parsed = json.loads(contents)
    return [Product.from_dict(row) for row in parsed["products"]]
