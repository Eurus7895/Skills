# Survey — what is in this repository

The first component. This file is what to read in its output and what to decide from it; which stages it
runs, which may fail without stopping it, and every flag are in [`pipeline.md`](pipeline.md).

**Checkpoint P1 closes this component**, and `analyze` will not run until it is decided.

```bash
python3 scripts/pipeline.py survey --root . --top 25
```

- **Read** the scanner's digest, every finding from the index validator, and the selected units with their
  fan-in.
- **Decide** whether to continue, rescan, or stop and report the repository is out of scope — and whether the
  scope this picked is the right one.

**If the scan reports `FAIL no source files found`, stop and say so.** The scanner parses Python, JavaScript,
TypeScript, Go, Rust, Java, Ruby, C and C++. Report which extensions were present and that this skill cannot
cover them; do not fall back to reading files and writing an unverifiable document.

An `E007`/`E008` finding means the tree changed under the scan — rerun. These never enter a retry loop with
the model; they are defects in a deterministic step.

The digest names the **assets** — README, packaging manifests, CI workflows, ADRs, configuration, examples —
with a count per kind. These are listed, never parsed. They are what a page about installation or conventions
may cite, and the absence of one is itself an answer: a repository with no ADR gets "no decision record
exists", not a rationale you worked out.

**The scope is a budget.** Every module in `units.txt` costs a model call, so the ranking keeps the top 25 by
fan-in plus every entry point. Change it with `--top` if the repository warrants it and say in the document
which cutoff you used; raise it deliberately, not by forgetting it. `units.txt` is the contract for the whole
run — everything outside it is covered in one line each, grouped by directory. **Read the warnings the
selection prints.** A repository whose modules import nothing from each other — standalone CLIs, scripts a
scheduler runs — has no fan-in to rank, and the cutoff it gets is arbitrary rather than considered; pick the
units by hand there and say that you did.

Ruff's import-usage annotation is advisory and additive. **An unused import is not evidence that a dependency
is unnecessary** — re-export, side effects, registration and dynamic discovery all look identical from here.
Report the count in the limitations with that caveat, and never propose removing an import as part of
documenting. `--policy disabled` if the user does not want an external tool invoked.

**Pause here — P1.** The scope is the one decision that cannot be corrected later without paying for the
analysis twice. Show the units, the cutoff and the warnings, and ask before spending the budget.
