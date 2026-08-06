"""Order pricing.

FIXTURE -- the code in this file is CORRECT. The failing test is the defect.

Pricing rules, in order:
  1. Sum the line items.
  2. Apply the percentage discount to that subtotal.
  3. Apply tax to the discounted amount.
  4. Add shipping, which is never taxed and never discounted.

Tax applies *after* the discount. A customer does not pay tax on money they did not
spend. This ordering is deliberate and is what the tests must assert.
"""

from decimal import Decimal, ROUND_HALF_UP

TAX_RATE = Decimal("0.10")


def _money(value):
    """Round to cents, half away from zero, the way an invoice does."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def subtotal(items):
    """Sum `items`, each a (unit_price, quantity) pair."""
    total = sum(Decimal(str(price)) * quantity for price, quantity in items)
    return _money(total)


def total(items, discount_percent=0, shipping=0):
    """Return the amount payable.

    Discount is applied to the subtotal, tax to the discounted amount, and shipping is
    added last, untaxed.

    Raises:
        ValueError: if `discount_percent` is outside 0-100.
    """
    if not 0 <= discount_percent <= 100:
        raise ValueError("discount_percent must be between 0 and 100")

    base = subtotal(items)
    discounted = base * (Decimal(100 - discount_percent) / Decimal(100))
    taxed = discounted * (Decimal(1) + TAX_RATE)
    return _money(taxed + Decimal(str(shipping)))
