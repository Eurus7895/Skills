"""Shopping cart.

FIXTURE -- this implementation is correct. The *test suite* is the defect.
"""


class Cart:
    def __init__(self):
        self._lines = {}

    def add(self, sku, quantity=1):
        """Add `quantity` of `sku`. Returns the new quantity for that SKU."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._lines[sku] = self._lines.get(sku, 0) + quantity
        return self._lines[sku]

    def remove(self, sku):
        """Remove `sku` entirely. Returns True if it was present, False otherwise."""
        return self._lines.pop(sku, None) is not None

    def count(self):
        """Total number of units across all lines."""
        return sum(self._lines.values())

    def apply_coupon(self, code, rates):
        """Return the discount rate for `code`, or 0.0 if it is unknown or expired.

        `rates` maps a coupon code to a (rate, active) pair.
        """
        rate, active = rates.get(code, (0.0, False))
        return rate if active else 0.0
