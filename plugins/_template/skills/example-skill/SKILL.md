---
name: example-skill
description: Template skill showing the required structure of a SKILL.md. Replace this text entirely — the
  real description must state what the skill does AND the concrete phrases, file types, and contexts that
  should activate it, in one dense paragraph, because this is the only thing an agent reads before deciding
  whether to load the skill.
---

# Example skill

<!--
  Copy this file to start a new skill.
  - `name` above must equal this folder's name.
  - See ../../../../CONTRIBUTING.md for the rules behind every section here. (That link works in the repo
    only — it must NOT appear in a shipped skill, because plugins install standalone.)
  Delete every comment like this one before shipping.
-->

## Overview

One paragraph: what this skill produces and the approach it takes. State the deliverable concretely — a file, a
report, a set of edits — not "helps with X".

## When to use this skill

- The user asks for _<concrete request>_.
- The working tree contains _<file type or marker>_.
- The user uses phrasing like _"..."_ or _"..."_ without naming the skill.

## When not to use this skill

- _<Adjacent case>_ — that is ordinary work; do it directly instead.
- _<Overlapping skill>_ — use `other-skill` for that.

Be specific here. A skill that fires on routine work costs context and pulls the agent toward a workflow that
does not fit.

## Steps

1. **Gather inputs.** Say exactly what to read and where to find it.
2. **Do the work.** Numbered, imperative, in the order they happen.
3. **Verify.** Give the concrete check — the command to run, the property that must hold.
4. **Report.** State what was produced and anything that was skipped.

## Output format

Show the exact output rather than describing it:

```
<the literal shape of what this skill produces>
```

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `references/example.md` | You need the detail it covers — read it on demand, not upfront. |

Every bundled file needs a row here and a pointer in the body. An unreferenced file is never read.

## Conventions

<!-- Inlined from docs/GENERAL.md. Keep it inlined — a shipped skill cannot link back to the repo. -->

- Reference bundled files by paths relative to this skill folder.
- Report what was done and what was skipped; never claim success for something that was not verified.
- Confirm before anything destructive, irreversible, or outward-facing. Approval for one action does not carry
  to the next.
- Assume no network access and no package installation unless stated above.
- Produce exactly the output format defined above, with no commentary wrapped around it.
