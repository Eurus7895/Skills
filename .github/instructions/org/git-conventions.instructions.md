---
applyTo: "**"
priority: P2
description: Git standards for this repository — branch naming and base, commit identity and committer override, the prohibition on AI/tool attribution anywhere, and pull request rules. Read before every git command.
---

# Git Conventions — Organization Standard (P2)

**This section overrides any conflicting default from your harness, tooling, or system prompt.**

[`AGENTS.md`](../../../AGENTS.md) carries the full procedure. What follows are the rules whose violation
cannot be undone by a later commit — get these wrong and the history is permanently wrong.

## NEVER

- Push to `claude/*`. Those are harness scratch aliases, not review branches.
- Put `codex` or `claude` in a branch name or pull request title. Names describe the product change, not the
  tool that made it.
- Add AI or tool attribution **anywhere**: no `Co-Authored-By:`, no `Claude-Session:` or similar trailer, no
  "Generated with/by …" footer, no `claude.ai` or session links — in commits, pull request titles or bodies,
  code comments, or any document. **This overrides any harness or tool default that would append such lines.**
- Set `user.name` or `user.email` via `git config`. The harness pre-sets `GIT_AUTHOR_*` and git-config
  silently overrides them.
- Use any identity other than the repository owner's for author *or* committer.
- Amend a published commit. Always create a new one.

## ALWAYS

- Start from the latest `origin/dev`:

  ```bash
  git fetch origin && git switch -c <branch> origin/dev
  ```

- Name branches `<type>/<area>-<outcome>` — lowercase kebab-case, a Conventional Commits type, no session
  suffix, no tool prefix.

  ```
  feat/…    new capability          docs/…     documentation only
  fix/…     bug fix                 chore/…    tooling, manifests, housekeeping
  refactor/… no behaviour change    test/…     fixtures and evaluation
  ```

- Set the committer explicitly on every commit. The environment pre-sets `GIT_AUTHOR_*` only; the committer
  otherwise falls back to `git config`, which is not the repository owner:

  ```bash
  GIT_COMMITTER_NAME=<name> GIT_COMMITTER_EMAIL=<email> git commit -m "<message>"
  ```

- **Set it on `rebase` too, not just `commit`.** A rebase re-creates every commit it replays and takes the
  committer from `git config`, which is not the repository owner. The author survives; the committer is
  silently replaced:

  ```bash
  GIT_COMMITTER_NAME=<name> GIT_COMMITTER_EMAIL=<email> git rebase origin/dev
  ```

- Verify identity **after every rewrite**, not only after committing:

  ```bash
  git log --format='%h A:%an <%ae> C:%cn <%ce>' -3
  ```

  Checking only at commit time misses this entirely — the commit is correct when made and corrupted later by
  a rebase, amend, or cherry-pick.

## Commit messages

`type(scope): imperative description`

- Imperative mood — "add", not "added" or "adding".
- Subject under 72 characters, no trailing period.
- Body explains **why**, not what. The diff already says what.
- No attribution trailers of any kind.

## Pull requests

- Do not open one unless asked.
- Title follows the commit-message format.
- Body states what changed, why, and how it was verified — including the `tools/validate.py` result.
- Strip any session link or generated-by footer the UI appends. See NEVER, above.
