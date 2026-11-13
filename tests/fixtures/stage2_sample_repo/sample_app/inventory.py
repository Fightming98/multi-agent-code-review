"""Small inventory helpers covered by the sample test suite."""


def total_quantity(items):
    """Return the sum of all item quantities."""
    return sum(item.get("quantity", 0) for item in items)


def low_stock(items, threshold=5):
    """Return SKUs whose quantity is below *threshold*."""
    return [item["sku"] for item in items if item.get("quantity", 0) < threshold]


def group_by_category(items):
    """Group items by category, defaulting to ``unknown``."""
    grouped = {}
    for item in items:
        key = item.get("category", "unknown")
        grouped.setdefault(key, []).append(item)
    return grouped
