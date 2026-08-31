from order_processor import processLegacyOrder


def submit_order(order_id):
    """Re-exports processLegacyOrder under a different name -- a caller of
    submit_order is an INDIRECT caller of processLegacyOrder that a single
    Grep for "processLegacyOrder" alone will miss.
    """
    return processLegacyOrder(order_id)
