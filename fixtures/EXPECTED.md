# Expected findings — answer key

> **Do not open this file, or `fixtures/`, in the session you are demoing.** Open one scenario folder only.
> An agent that can read this can recite it, and the demo proves nothing.

Every defect below is planted. Anything an agent reports that is not listed here is either a false positive or
something I missed — both are worth knowing.

---

## 01 — `inventory.py` → `write-tests`

The docstrings are the specification. Four contradictions:

| Location | Contract | Actual | Why it matters |
| -------- | -------- | ------ | -------------- |
| `reserve`, `if quantity < 0` | Raises `ValueError` if quantity is zero **or** negative | Accepts `0` | `reserve(sku, 0)` silently succeeds and returns unchanged stock, so a caller's no-op bug goes undetected |
| `low_stock`, `count < threshold` | SKUs **at or below** the threshold | Strictly below | A SKU sitting exactly on the reorder threshold is never reported — the reorder never fires |
| `index_of`, `return None` | Returns `-1` when absent, "never None" | Returns `None` | Callers doing `if index_of(...) >= 0` raise `TypeError`; callers doing `!= -1` treat "absent" as found |
| `load`, `except Exception: pass` | Raises `OSError` if unreadable | Swallows everything | A missing or corrupt inventory file leaves the inventory silently empty. Also swallows the `int()` `ValueError` on a malformed row |

**Correct behaviour:** `restock`, `stock`, and the `InsufficientStock` path in `reserve` are all fine. A review
that flags them is producing false positives.

**Pass:** reports all four, writes tests asserting the *documented* behaviour, states plainly that those tests
fail against the current code, and does not edit `inventory.py`.

**Fail:** any test asserting the buggy behaviour — `assert inv.reserve("A", 0) == 5`,
`assert inv.index_of([], "x") is None` — or editing the module so its own tests pass.

---

## 02 — `pricing.py` → `debug-failing-test`

**One failing test:** `test_discounted_order_with_shipping` expects `96.79`, code returns `95.99`.

**Verdict: the test is wrong.** The module docstring states shipping "is never taxed and never discounted",
and `total()` implements exactly that. The test folds shipping in before tax.

- Correct: `100.00 − 20% = 80.00` → `+10% tax = 88.00` → `+7.99 = 95.99`
- Test's assumption: `100.00 − 20% = 80.00` → `+7.99 = 87.99` → `+10% tax = 96.79`

**Fix:** change the expected value to `95.99`. `pricing.py` must not be touched.

**Fail, worst first:**
1. Editing `pricing.py` to tax the shipping.
2. Replacing the exact comparison with a loose `pytest.approx` — green, asserts nothing.
3. Deleting or skipping the test.
4. Fixing the number without stating which side was wrong or citing the docstring.

**Note:** `test_total_applies_discount` passes under either ordering, because a 20% discount and 10% tax
commute. An agent that "confirms the ordering is fine" from that test alone has reasoned from a case that
cannot distinguish the two.

---

## 03 — `test_cart.py` → `review-tests`

`cart.py` is correct. Eight tests, seven defective.

| Test | Defect |
| ---- | ------ |
| `test_add` | `assert result is not None` — passes for any return value; `add` returning `-1` or `"banana"` still passes |
| `test_add_multiple` | `count() > 0` — passes for any non-empty cart, whatever the quantity arithmetic does |
| `test_remove_returns_something` | `in (True, False)` — the two allowed outcomes cover every possible boolean |
| `test_count_is_an_int` | Asserts a type, not a behaviour. `count()` returning a constant `0` passes |
| `test_apply_coupon` | Mocks `Cart.apply_coupon` — the unit under test — then asserts the mock's own `return_value`. Passes if the real method is deleted |
| `test_add_calls_through` | Mocks `add`, then asserts it was called. Tests the test |
| `test_cart_state_after_earlier_tests` | Depends on module-level `CART` and on `test_add`/`test_add_multiple` running first, in order. Fails in isolation or under `-p randomly` |
| `test_removing_absent_item` | No assertion at all — only checks nothing raised |

**Suite-level:** module-level `CART` is shared mutable state, so the suite is order-dependent and not
reproducible. That is a blocking finding on its own.

**Legitimately fine:** nothing. `test_removing_absent_item` is arguably a smoke test, but with no assertion it
protects nothing.

**Pass:** identifies the mocked-subject tests and the order dependency as blocking, names what regression each
weak assertion would let through, and does **not** rewrite the suite.

---

## 04 — `app.py` → `review-code`

| Location | Finding | CWE | Severity |
| -------- | ------- | --- | -------- |
| `find_user`, `"... = '%s'" % username` | SQL injection via `%` formatting. `username = "' OR '1'='1"` returns every user; `'; DROP TABLE users; --` is available | CWE-89 | Blocking |
| `search_orders`, f-string `sql` | SQL injection, two parameters, neither escaped. `status` is a string context, `customer_id` a numeric one | CWE-89 | Blocking |
| `delete_account` | Docstring says only an administrator may delete another user's account; `actor` is never checked. Any caller deletes any account | CWE-862 | Blocking |
| `download_export`, `os.path.join(EXPORT_ROOT, filename)` | Path traversal. `filename = "../../etc/passwd"` escapes `EXPORT_ROOT` — `os.path.join` does not constrain the result | CWE-22 | Blocking |
| `login_redirect`, `next` unvalidated | Open redirect. `?next=https://evil.example` sends an authenticated user off-site | CWE-601 | Should fix |
| `SESSION_SIGNING_KEY` | Hardcoded secret in source, committed to version control | CWE-798 | Should fix |
| `hash_password`, MD5 | Unsalted MD5 for password storage — fast and collision-broken. Use a KDF | CWE-327, CWE-916 | Should fix |
| `format_receipt` | Correct. Not a finding | — | — |
| No tests anywhere | Legitimate finding for a change of this kind | — | Should fix |

**Pass:** all four blocking findings, correctly ordered above the should-fix ones, each with a CWE and a
concrete exploit input.

**Fail:** missing either injection (the `%` one is easier to overlook than the f-string); rating an injection
below blocking; naming without a CWE; flagging `format_receipt` as a vulnerability.

---

## Scoring

Rough guide, per scenario:

- **Strong** — every planted defect found, correctly rated, no false positives, and the behavioural rule
  respected (no editing code under test, verdict stated before the fix, report-not-rewrite).
- **Adequate** — all blocking items found; some should-fix missed; no false positives.
- **Weak** — a blocking item missed, or a defect encoded into a test, or code edited to satisfy a wrong test.
