<!-- GENERATED FILE -- DO NOT EDIT.
     Source: shared/references/review-standard.md
     Regenerate: python3 tools/materialize.py -->

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

| Label | Use for |
| ----- | ------- |
| `issue:` | A defect. Pair with **blocking** or **should fix**. |
| `suggestion:` | A concrete alternative that is better, with the reason. |
| `nit:` | Non-blocking. The author may decline without justifying. |
| `question:` | You do not understand the intent and cannot judge it yet. Ask before asserting. |
| `praise:` | A decision worth keeping. Use sparingly and only where it is genuinely load-bearing. |

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
| Untrusted input reaching a query, shell, or `eval` | CWE-89, CWE-78, CWE-94 |
| Missing or incorrect authorization on a state change | CWE-862, CWE-863 |
| Secrets, tokens, or keys in source, logs, or error messages | CWE-798, CWE-532 |
| Path built from user input | CWE-22 |
| Unvalidated redirect or SSRF-able URL | CWE-601, CWE-918 |
| Weak or missing crypto, homemade crypto | CWE-327, CWE-330 |
| Deserializing untrusted data | CWE-502 |
| Missing bounds or integer overflow check | CWE-125, CWE-190 |

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

## Not reviewed
<Anything skipped and why — generated files, vendored code, areas needing domain context you lack.>
```

Rules for the output:

- Every finding carries `file:line`. A finding without a location cannot be acted on.
- **Report "no blocking findings" plainly when that is the answer.** Do not manufacture findings to look
  thorough — a review that always finds something teaches the author to ignore reviews.
- State what you did not review. Silence reads as "I checked that", which is worse than admitting the gap.
