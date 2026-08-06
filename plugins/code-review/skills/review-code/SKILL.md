---
name: review-code
description: Review production code — a diff, a pull request, a branch, or the working tree — for correctness, security, and maintainability, reporting severity-ordered findings with file:line, Conventional Comments labels, and CWE names for security issues. Use whenever the user says "review this", "review my changes", "look over this PR", "is this code okay", "check this before I merge", "any problems with this", asks for a second opinion on a diff, or wants a security or correctness pass over code they wrote.
---

# Review code

## Overview

Review a change against the standard in `references/review-standard.md`: approve when it definitely improves
overall code health, even if imperfect. Findings are ordered by severity, each carrying `file:line`, a
Conventional Comments label, and a concrete failure scenario — the input or state that breaks it.

A finding you cannot attach a failure scenario to is a preference, not a defect.

## When to use this skill

- "Review my changes" / "review this PR" / "look this over before I merge".
- A pasted diff or a branch to compare against a base.
- "Is this safe?" / "any security problems here?"
- The user wants a second opinion before shipping.

## When not to use this skill

- **Tests are the subject** — use `review-tests` from the `testing` plugin.
- **A test is failing** — use `debug-failing-test`.
- **The user wants the code fixed, not judged** — that is ordinary work; do it directly. This skill reports.
- **A formatter or linter already covers it** — do not hand-review whitespace, import order, or quote style.
  Say "run the linter" and move on.

## Steps

1. **Establish scope.** Determine exactly what is under review — `git diff <base>...HEAD`, a named PR, staged
   changes, or specific files. State the scope in the output. Reviewing more than asked wastes the author's
   attention; reviewing less hides defects.

2. **Understand the intent.** Read the PR description, commit messages, or linked issue. You cannot judge
   whether code is correct without knowing what it is meant to do. If intent is unclear, use `question:`
   rather than asserting a defect.

3. **Read `references/review-standard.md`.** It carries the core rule, the severity ladder, the Conventional
   Comments labels, the CWE security checklist, and the output contract.

4. **Detect the stack.** Run `python3 scripts/detect_stack.py <repo-root>` to learn the ecosystem and whether
   tests exist. This tells you which idioms apply and whether "no test for this branch" is a fair finding.

5. **Review in passes**, in this order — stop escalating severity as you go down:
   - **Correctness** — does it do what it claims? Off-by-one, inverted condition, unhandled `None`/`nil`/error
     return, wrong operator precedence, resource never released, silent truncation.
   - **Security** — walk the CWE checklist in the reference. Untrusted input reaching a query, shell, path, or
     deserializer; missing authorization on a state change; secrets in source or logs.
   - **Error handling** — what happens on failure? Swallowed exceptions, errors logged and continued past,
     partial writes with no rollback.
   - **Concurrency** — shared mutable state, missing synchronization, assumptions about ordering.
   - **Tests** — new behavior with no test covering it, especially new branches and error paths.
   - **Maintainability** — misleading names on public APIs, duplicated logic that will drift, dead code, a
     function doing three things.

6. **Check what the diff does not show.** Callers of a changed signature, other implementations of a changed
   interface, migrations paired with schema changes, docs contradicting new behavior. Most real defects in a
   review live outside the diff.

7. **Write the findings** in the output contract from the reference.

## Hard rules

- **Every finding needs `file:line` and a concrete failure scenario.** "This could be cleaner" is not a
  finding.
- **Facts beat preferences.** "This allocates on every call in a hot loop" is a finding. "I'd use a map here"
  is not, unless you can name the cost.
- **Style is the linter's job**, and the style guide is the authority. Do not relitigate it.
- **Report "no blocking findings" plainly** when that is the answer. A review that always finds something
  teaches the author to ignore reviews.
- **State what you did not review** and why. Silence reads as "I checked that".
- This skill reports; it does not edit. Ask before changing any file.

## Output format

Use the output contract in `references/review-standard.md`:

```markdown
## Review summary
<what the change does; verdict — approve / approve with fixes / needs work>

## Findings

### Blocking
1. **`src/auth.py:88`** — issue: user-supplied `next` parameter is redirected to without validation.
   A request with `?next=https://evil.example` sends the authenticated user off-site with their
   session intact (CWE-601). Allow-list the redirect targets or require a relative path.

### Should fix
### Nits

## Not reviewed
<skipped areas and why>
```

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `references/review-standard.md` | Step 3, always — the criteria, labels, CWE checklist, and output contract. |
| `scripts/detect_stack.py` | Step 4. Run it; you do not need to read it. Filesystem only, no network, no writes. |

## Conventions

- Reference bundled files by paths relative to this skill folder.
- Report what was reviewed and what was skipped; never imply coverage you did not have.
- Confirm before editing anything — this skill produces a report, not a patch.
- Assume no network access and no package installation.
- Produce exactly the output contract above, with no commentary wrapped around it.
