from order_processor import processLegacyOrder


def test_processes_order():
    assert processLegacyOrder("A1") == "processed:A1"
