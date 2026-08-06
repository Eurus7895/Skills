# code-review

Review code against an established standard, and set up the rules files that keep agents aligned with a
repository's conventions.

Findings follow [Google's *Standard of Code Review*](https://google.github.io/eng-practices/review/reviewer/standard.html)
— approve when the change definitely improves overall code health — labelled with Conventional Comments
(`issue:`, `suggestion:`, `nit:`, `question:`) and named with CWE identifiers for security issues.

## Install

```bash
copilot plugin marketplace add Eurus7895/Skills
copilot plugin install code-review@eurus-skills
```

## Skills

- **`review-code`** — review a diff, PR, branch, or working tree for correctness, security, error handling,
  concurrency, test coverage, and maintainability. Severity-ordered findings, each with `file:line` and a
  concrete failure scenario. Fires on "review this", "check before I merge", "any security problems".
- **`setup-review-rules`** — generate `AGENTS.md`, `.github/copilot-instructions.md`, and a project-specific
  review checklist from what the repo actually does. Fires on "set up rules for this repo", "add AGENTS.md",
  "onboard this repo for agents".

## Notes

- `review-code` reports; it does not patch. It asks before editing anything.
- `setup-review-rules` never overwrites an existing rules file without confirmation, and never states a
  convention it did not observe in the repository.
- `references/review-standard.md` and `scripts/detect_stack.py` are generated from `shared/` in the source
  repository. Do not edit them here — edit `shared/` and run `python3 tools/materialize.py`.
