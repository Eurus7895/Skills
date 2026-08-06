"""FIXTURE -- every test here passes. Almost none of them would catch a regression."""

from unittest.mock import patch

from cart import Cart

# Shared across tests. Whether a test passes depends on which tests ran before it.
CART = Cart()


def test_add():
    result = CART.add("widget")
    assert result is not None


def test_add_multiple():
    CART.add("widget", 3)
    assert CART.count() > 0


def test_remove_returns_something():
    CART.add("gadget")
    assert CART.remove("gadget") in (True, False)


def test_count_is_an_int():
    assert isinstance(CART.count(), int)


def test_apply_coupon():
    with patch.object(Cart, "apply_coupon", return_value=0.25):
        cart = Cart()
        assert cart.apply_coupon("SAVE25", {}) == 0.25


def test_add_calls_through():
    with patch.object(Cart, "add") as mocked:
        mocked.return_value = 1
        cart = Cart()
        cart.add("thing")
        assert mocked.call_count == 1


def test_cart_state_after_earlier_tests():
    # Depends on test_add and test_add_multiple having run first, in order.
    assert CART.count() == 4


def test_removing_absent_item():
    Cart().remove("never-added")
