def cheapest(products):
    best = None
    for product in products:
        if not product.in_stock:
            continue
        if best is None or product.price < best.price:
            best = product
    return best
