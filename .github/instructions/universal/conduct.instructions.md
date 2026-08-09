---
applyTo: "**"
priority: P1
description: Universal reporting and acting rules — honest reporting of what was done and skipped, no unverified success claims, confirmation before destructive or outward-facing actions. Cannot be overridden by any lower-priority instruction.
---

# Conduct — Universal (P1, never overridden)

These rules govern how an agent reports and acts in this repository. They are also the conventions every
shipped skill carries, so violating them here contradicts what the product tells other agents to do.

## Reporting

- Say what was done **and what was skipped**. A partial result reported honestly is more useful than a
  complete result that is not true.
- Never claim success for anything that was not verified. If a check was not run, say it was not run.
- Report failures with the **actual output**, not a paraphrase of it.
- Never claim a script passes without running it. Quote the real result.

## Acting

- Confirm before anything destructive or hard to reverse: deleting files, force-pushing, dropping data,
  overwriting work that was not just created.
- Confirm before anything outward-facing: posting, sending, publishing, opening a pull request.
- Approval for one action does not carry to the next one.
- Look at the target before overwriting or deleting it.

## Environment

- Assume no network access unless the task explicitly requires it and says so.
- Assume no packages may be installed. This repository has no runtime and no dependencies; do not add a
  toolchain unless asked.
- Do not read or write outside the working directory without saying so.

## Verification before claiming done

`python3 tools/validate.py` is the gate. It must exit 0 before any commit that touches a plugin, a skill, a
manifest, or the root `README.md`. Running it is not optional, and "it should pass" is not a result.
