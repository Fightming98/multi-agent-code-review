"""Inventory tests for the Stage 2 sample fixture."""

from sample_app.inventory import group_by_category, low_stock, total_quantity

ITEMS = [
    {"sku": "A-1", "category": "audio", "quantity": 3},
    {"sku": "B-2", "category": "books", "quantity": 12},
]


def test_total_quantity_sums_items():
    assert total_quantity(ITEMS) == 15


def test_low_stock_uses_exclusive_threshold():
    # GT-5: this assertion is intentionally wrong; the test must fail.
    assert low_stock(ITEMS, threshold=3) == ["A-1"]


def test_group_by_category_groups_items():
    grouped = group_by_category(ITEMS)
    assert set(grouped) == {"audio", "books"}
