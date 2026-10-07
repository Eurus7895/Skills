# Review standard

The criteria and output format every review in this plugin follows. Based on Google's
*The Standard of Code Review*, Conventional Comments, and CWE naming for security findings.

## The core rule

> Approve the change when it **definitely improves overall code health**, even if it is not perfect.

There is no perfect code — only better code. A reviewer who blocks on hypothetical improvements costs more
than the defects they prevent. Two corollaries:

- **Facts and data beat preferences.** "This allocates on every call" is a finding. "I would have used a map"
  is not, unless you can name the cost.
- **Style is settled by the style guide**, not by the reviewer. If the repo has a linter or formatter, its
  output is the authority and you do not duplicate it by hand.

## Severity ladder

Order every set of findings by this, highest first.

| Severity | Means | Examples |
| -------- | ----- | -------- |
| **Blocking** | Wrong behavior, data loss, or a security hole reaches users | Incorrect logic, unhandled error path, injection, secret in source, race on shared state |
| **Should fix** | Real risk or maintenance cost, not immediately harmful | Missing test for a new branch, swallowed exception, unbounded growth, misleading name on a public API |
| **Nit** | Genuine improvement, author may decline | Local naming, redundant comment, minor duplication |

A finding you cannot attach a concrete failure scenario to is a nit at most. If you cannot describe the input
that breaks it, you have a preference, not a defect.

## Comment format — Conventional Comments

Every comment starts with a label so severity is explicit and the output can be parsed:

```
<label>: <one-line claim>

<why it matters — the concrete failure, not a restatement>
<what to do instead, when it is not obvious>
```

| Label | Use for | Goes under |
| ----- | ------- | ---------- |
| `issue:` | A defect. | **Blocking** or **Should fix** |
| `suggestion:` | A concrete alternative that is better, with the reason. | **Should fix** or **Nits**, by its cost |
| `nit:` | Non-blocking. The author may decline without justifying. | **Nits** |
| `question:` | You do not understand the intent and cannot judge it yet. Ask before asserting. | **Questions** |
| `praise:` | A decision worth keeping. Use sparingly and only where it is genuinely load-bearing. | one line in the summary |

A question whose answer decides whether something is a defect holds the verdict at **needs work** until it is
answered.

Good:

```
issue: `parse_config` returns None on a malformed file, and every caller dereferences it.

A config with a stray tab reaches line 44, returns None, and callers crash with AttributeError
instead of the intended "invalid config" error. Raise ConfigError and let the caller decide.
```

Bad — no failure scenario, no action:

```
This error handling looks fragile.
```

## Security checklist

Name the category. "This is unsafe" is not actionable; "CWE-89 SQL injection" is.

| Check | CWE |
| ----- | --- |
| Untrusted input rendered into HTML, a template, or the DOM without contextual escaping | CWE-79 |
| Untrusted input reaching a query, shell, or `eval` | CWE-89, CWE-78, CWE-94 |
| A state-changing request accepted without a CSRF token or same-site protection | CWE-352 |
| Missing or bypassable authentication on a sensitive function or endpoint | CWE-306, CWE-287 |
| Missing or incorrect authorization on a state change | CWE-862, CWE-863 |
| Secrets, tokens, or keys in source, logs, or error messages | CWE-798, CWE-532 |
| Path built from user input | CWE-22 |
| File upload without type, size, and destination checks | CWE-434 |
| Unvalidated redirect or SSRF-able URL | CWE-601, CWE-918 |
| Weak or missing crypto, homemade crypto | CWE-327, CWE-330 |
| Deserializing untrusted data | CWE-502 |
| Missing bounds check, integer overflow, use after free | CWE-125, CWE-787, CWE-190, CWE-416 |

The table is a floor. A weakness it does not list still gets named by its CWE id.

## Output contract

```markdown
## Review summary

<2–3 sentences: what the change does, and the verdict — approve, approve with fixes, or needs work.>

## Findings

### Blocking
1. **`path/to/file.py:42`** — issue: <claim>
   <failure scenario: the input or state that breaks it, and the result>
   <suggested fix>

### Should fix
...

### Nits
...

### Questions
1. **`path/to/file.py:42`** — question: <what you need to know before you can judge it>

## Not reviewed
<Anything skipped and why — generated files, vendored code, areas needing domain context you lack.>
```

Rules for the output:

- Every finding carries `file:line`. A finding without a location cannot be acted on.
- Every Blocking or Should-fix finding carries a failure scenario. A nit carries the improvement.
- Omit an empty **Questions** section; keep the three severity headings even when empty.
- **Report "no blocking findings" plainly when that is the answer.** Do not manufacture findings to look
  thorough — a review that always finds something teaches the author to ignore reviews.
- State what you did not review. Silence reads as "I checked that", which is worse than admitting the gap.
