"""Reporting helpers intentionally left without tests to lower coverage."""


def format_line(item):
    """Render one inventory line."""
    return f"{item['sku']}: {item['quantity']}"


def render_report(items):
    """Render all inventory lines."""
    return "\n".join(format_line(item) for item in items)


def summarize(items):
    """Summarize an inventory list."""
    total = sum(item["quantity"] for item in items)
    return {"count": len(items), "total": total}
