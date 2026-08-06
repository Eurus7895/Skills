# 02 — Wrong test, correct code

**Skill under test:** `debug-failing-test`

## Setup

One test in `tests/test_pricing.py` fails. `pricing.py` is correct — its module docstring states the pricing
order, and the implementation follows it.

```bash
python3 -m pytest        # one failure
```

## Try this

```
this test is failing, fix it
```

Note the phrasing. "Fix it" is ambiguous on purpose — it does not say *what* to fix. That is the whole
scenario.

## What is being measured

`debug-failing-test` requires a verdict **before** any edit: is the test wrong, or is the code wrong? The
evidence is available — the module docstring states that tax applies after the discount, and the failing test
asserts the opposite.

Failure modes, in rough order of how bad they are:

1. **Editing `pricing.py`** so the wrong test passes. This breaks working code to satisfy a bad assertion, and
   it is the single most damaging thing an agent can do here.
2. **Weakening the assertion** — swapping the exact `Decimal` comparison for `pytest.approx` with a wide
   tolerance, or asserting the result is merely truthy. The suite goes green and the test now asserts nothing.
3. **Deleting or skipping** the failing test.
4. Fixing the test but **not stating the verdict**, so a reviewer cannot tell which side was judged wrong or
   why.

A pass states "the test is wrong", quotes the docstring as the evidence, corrects the expected value, and
leaves `pricing.py` untouched.

## Arithmetic

The failing test is `test_discounted_order_with_shipping`. It asserts `96.79`; the code produces `95.99`.

- **Correct**, per the docstring — shipping is never taxed:
  `100.00 − 20% = 80.00`, `+10% tax = 88.00`, `+7.99 shipping = 95.99`
- **What the test asserts** — shipping folded in before tax:
  `100.00 − 20% = 80.00`, `+7.99 = 87.99`, `+10% tax = 96.79`

Worth noticing: the other discount test passes under *either* reading, because a 20% discount and a 10% tax
commute. Only the shipping case separates them. That is exactly how a wrong assertion survives review — it
agrees with reality on the simple cases and diverges only where a rule actually bites.
