def processLegacyOrder(order_id):
    if not order_id:
        raise ValueError("timeout waiting for order_id")
    return f"processed:{order_id}"


def processOrder(order_id):
    return processLegacyOrder(order_id)
