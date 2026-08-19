# docs

Write a repository's architecture documentation from its real dependency graph, not from what the model
remembers reading.

The shape is what makes the result checkable:

```
parse with a scanner  ->  describe each module with its real neighbours  ->  verify every claim  ->  write
```

Structure is a fact extracted by code. Judgement happens afterwards, once each module's role can be stated
against the modules that actually import it. Nothing ships that the graph does not support.

## Install

```bash
copilot plugin marketplace add Eurus7895/Skills
copilot plugin install docs@CopilotBox
```

## Skills

- **`document-codebase`** — parses the repository with `scan_repo.py` (Python via `ast`, other languages by
  import regex), ranks modules by fan-in, describes each one with its real importers supplied, then
  cross-checks every dependency claim against the graph before writing the document. Fires on "document this
  repo", "write architecture docs", "explain how this codebase fits together", "map the dependencies".

## Notes

- **Import edges are not call edges.** `scan_repo.py` records imports; it builds no call graph. "A imports B"
  is verifiable against the graph, "A calls B.f()" is not — the latter may only be written after the call site
  has been read, and must cite that line. The skill downgrades any call claim that lacks one, and reports how
  many it downgraded.
- **Approximate data labels itself.** Python is parsed exactly with `ast`. JavaScript, TypeScript, Go, Rust,
  Java, Ruby, C and C++ are approximated by import regex; those records carry `"exact": false`, and any claim
  resting on them is marked *(approximate)*.
- **`--detail` covers classes.** Base classes, methods with parameters and visibility, and attributes from both
  the class body and `self` assignments — Python only, because regex can find a class name but not its bases,
  and a half-filled record reads like a complete one. A base class links to a defining file only when the
  import resolves **and** that file defines a class by that name.
- **Coverage is reported, not assumed.** The document says how many files were scanned, how many were parsed
  exactly, how many claims were checked against the graph, how many failed, and what was skipped — including
  symlinks resolving outside the scanned root.
- Bundled scripts are Python 3, stdlib only. They read the working tree and write their declared outputs
  (`structure.json`, and the document itself) into the working directory. No network, no installs.
- `scan_repo.py` and `assemble.py` are authored in `shared/scripts/` and materialized here. Edit the source and
  run `python3 tools/materialize.py`; never edit the generated copies.
