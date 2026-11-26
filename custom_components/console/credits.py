"""Usage is shown to a household in credits, never dollars: one credit is one US cent of AI use."""

from __future__ import annotations


def credits(usd: float) -> float | int:
    """Dollars as credits: whole numbers from 10 up, one decimal below that, two below a tenth."""
    value = float(usd or 0.0) * 100
    if value >= 10:
        return round(value)
    if value >= 0.1:
        return round(value, 1)
    return round(value, 2)
