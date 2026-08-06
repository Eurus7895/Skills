# 04 — Security review

**Skill under test:** `review-code`

> **This code is intentionally vulnerable.** It is a measurement target. Do not copy it, do not deploy it, and
> do not treat any part of it as an example of how to do something.

## Setup

`app.py` is a small account service with several planted vulnerabilities of differing severity, mixed in with
correct code and at least one purely cosmetic issue.

## Try this

```
review app.py
```

or

```
any security problems in this file?
```

## What is being measured

Three things, in order of importance:

1. **Detection** — are the real vulnerabilities found at all?
2. **Naming** — `review-code` requires security findings to carry a CWE identifier. "This looks unsafe" is not
   actionable; "CWE-89 SQL injection" is.
3. **Ordering and discrimination** — blocking findings must sort above should-fix, and both above nits. A
   review that lists a formatting nit alongside a remote-code-execution path has not done the reader's
   thinking for them.

Every finding also needs `file:line` and a concrete failure scenario — the specific input that exploits it,
not a category label.

## Failure modes

- **Missing one.** The injection in the f-string query is easier to see than the one built with `%`; a review
  that catches one and not the other is incomplete.
- **Under-rating.** Reporting an injection as "should fix" rather than blocking.
- **Vague naming.** "Potential security issue" with no CWE and no exploit input.
- **False positives.** At least one function here is fine. Flagging it — or flagging the cosmetic issue as a
  security problem — is its own kind of failure, and `review-code` explicitly warns against manufacturing
  findings to look thorough.
- **Missing the non-injection issues.** Not every vulnerability here is an injection.

## Note on scope

There are no tests in this scenario, and that absence is itself a legitimate finding for a change of this
kind. A review that notes it has read the situation correctly.
