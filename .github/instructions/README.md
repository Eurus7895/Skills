# Instructions

Path-scoped instructions for agents working **in this repository**. Copilot applies a file automatically when
the file being worked on matches its `applyTo` glob — no agent decision, no loading step.

## Why these exist alongside `CONTRIBUTING.md`

`CONTRIBUTING.md` is the normative standard and explains *why* each rule exists. It only helps if the agent
reads it first. These files carry the operative rules and are applied **mechanically, by path**. Where they
disagree, `CONTRIBUTING.md` is authoritative and the instruction file is the bug — fix it.

## Tiers

| Tier | Scope | Priority |
| ---- | ----- | -------- |
| `universal/` | Every file. Safety and conduct. | P1 |
| `org/` | Every file. Cross-project standards. | P2 |
| `domain/` | Scoped by path to a kind of work. | P3 |
| `project/` | Every file. Facts about this repository. | P4 |

| File | `applyTo` |
| ---- | --------- |
| `universal/safety.instructions.md` | `**` |
| `universal/conduct.instructions.md` | `**` |
| `org/git-conventions.instructions.md` | `**` |
| `domain/skill-authoring.instructions.md` | `**/SKILL.md` |
| `domain/manifests.instructions.md` | `**/plugin.json`, `**/marketplace.json`, `**/shared.manifest` |
| `domain/scripts.instructions.md` | `tools/**/*.py`, `shared/**/*.py`, `plugins/**/*.py` |
| `project/repo-layout.instructions.md` | `**` |

## Why there is no `fixtures/**` instruction

Deliberately absent. An instruction scoped to `fixtures/**` is injected automatically whenever anything under
that path is touched — and that includes a session where an agent is **being evaluated** on a scenario. The
glob cannot distinguish an author from a subject.

Two concrete failures follow, and both are self-defeating:

- Any rule that names what is planted in a scenario becomes a **partial answer key**, handed to the agent
  before it starts looking.
- "Never repair a fixture" is correct for a contributor and **wrong for the agent under test** — scenario 02
  is passed by correcting the wrong test's expected value.

Fixture rules therefore live in [`CONTRIBUTING.md`](../../CONTRIBUTING.md), which is read by authors and does
not auto-inject.

## On `priority`

`priority` is **not a platform-enforced field.** As far as is documented, Copilot honours `applyTo` and
`description`; `priority` is read as ordinary text. It records intent — which rule is meant to win when two
conflict — and nothing mechanically enforces "P1 cannot be overridden."

Write as though it is not enforced, because it is not. Do not rely on a P1 file to cancel a contradictory P3
file; remove the contradiction instead.

## These do not ship

Instruction files are repository configuration. They are **not** copied into an installed plugin and have no
effect on anyone who installs from this marketplace.

A rule that must hold when a skill runs on someone else's machine belongs in the `SKILL.md` body — see
[`project/repo-layout.instructions.md`](project/repo-layout.instructions.md).
