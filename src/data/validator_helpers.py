from __future__ import annotations

from datetime import datetime
from typing import Any


def validate_price_row(price: Any, index: int, get_attr) -> tuple[bool, str | None]:
    time_val = get_attr(price, "time")
    if not time_val:
        return False, f"Price[{index}]: missing time"

    open_val = get_attr(price, "open", 0)
    high_val = get_attr(price, "high", 0)
    low_val = get_attr(price, "low", 0)
    close_val = get_attr(price, "close", 0)
    volume_val = get_attr(price, "volume", 0)

    if open_val <= 0 or high_val <= 0 or low_val <= 0 or close_val <= 0:
        return False, f"Price[{index}]: prices must be positive"
    if high_val < max(open_val, close_val):
        return False, f"Price[{index}]: high < max(open, close)"
    if low_val > min(open_val, close_val):
        return False, f"Price[{index}]: low > min(open, close)"
    if volume_val < 0:
        return False, f"Price[{index}]: volume must be non-negative"
    try:
        datetime.strptime(str(time_val), "%Y-%m-%d")
    except ValueError:
        return False, f"Price[{index}]: invalid date format"
    return True, None
