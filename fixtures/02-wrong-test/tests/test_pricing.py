"""FIXTURE -- one of these tests asserts the wrong thing. The code is correct."""

from decimal import Decimal

import pytest

from pricing import subtotal, total


def test_subtotal_sums_line_items():
    assert subtotal([("10.00", 2), ("5.50", 1)]) == Decimal("25.50")


def test_total_adds_tax():
    # 100.00 + 10% tax
    assert total([("100.00", 1)]) == Decimal("110.00")


def test_total_applies_discount():
    # 100.00 - 20% = 80.00, + 10% tax = 88.00
    assert total([("100.00", 1)], discount_percent=20) == Decimal("88.00")


def test_discounted_order_with_shipping():
    # 100.00 - 20% = 80.00, + 7.99 shipping = 87.99, + 10% tax = 96.79
    assert total(
        [("100.00", 1)], discount_percent=20, shipping="7.99"
    ) == Decimal("96.79")


def test_rejects_discount_over_100():
    with pytest.raises(ValueError):
        total([("10.00", 1)], discount_percent=101)
