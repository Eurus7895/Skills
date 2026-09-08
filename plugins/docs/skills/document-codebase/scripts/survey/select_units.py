#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/survey/select_units.py
# Regenerate: python3 tools/materialize.py
"""Choose the modules this run describes in full, by how much of the repository leans on them.

    python3 scripts/select_units.py --index .docs-build/structure.json \\
        --out .docs-build/units.txt --top 25

Every module named here costs a model call, and the ones worth that call are the ones
other modules depend on. Rank by fan-in, keep the top N, and add every entry point --
a way into the system earns a paragraph whether or not anything imports it.

`units.txt` is a contract: `derive_claims.py` claims exactly these modules, `assemble.py`
fails on any of them that came back without a row, and `quality_docs.py` measures coverage
against them and counts everything else apart. Edit the selection here, not afterwards.

**Fan-in is a heuristic, and this prints when it is a bad one.** A repository of standalone
programs -- CLIs invoked by a shell, scripts run by a scheduler -- imports nothing from
itself, so every fan-in is 0 and the ranking is arbitrary. The warning says so rather than
letting an arbitrary top 25 read like a considered one.

Ties break by path, so the same index always selects the same modules.

Standard library only. Exit codes: 0 ok, 2 input error, 3 internal error.
"""

import argparse
import json
import os
import sys


def fail(message, code=2):
    sys.stderr.write("FAIL  %s\n" % message)
    return code


def select(index, top):
    """The paths to describe in full, and why each one is in the list.

    Returns `(paths, reasons, ranked)` -- `reasons` maps a path to `fan_in`,
    `entry_point` or both, and `ranked` is the fan-in ordering the cutoff was taken from.
    """
    fan_in = index.get("fan_in") or {}
    # Not tests. A test file is evidence that the code works, not a part of the system a
    # reader is being introduced to: documenting it spends the budget describing scaffolding
    # and puts `test_parser.py` in a module reference beside the parser. The scanner already
    # marks them, the gate's fallback budget already skips them, and the selection did not --
    # so a repository with a large suite spent most of its units on it. A reader who wants
    # the tests is told how to run them, on the page the operations analysis fills.
    #
    # Only files that define something. A module with no symbol has nothing to anchor a
    # statement to -- `validate_analysis` requires a statement to name something that is
    # in the file it describes, and `assemble` requires a fragment citing a derived
    # claim, of which an empty `__init__.py` has none. Selecting one puts a unit in the
    # budget that no amount of work can satisfy: the assembler fails the run for a unit
    # with no row, and the coverage it drags down cannot be recovered. The gate's own
    # fallback budget has always filtered on this; the selection did not, and the two
    # disagreeing is what put empty package markers in `units.txt`.
    known = sorted(record["path"] for record in index.get("files", ())
                   if record.get("symbols") and not record.get("is_test"))
    # Rank every scanned file, not every key of `fan_in`: the scanner builds that map by
    # counting incoming edges, so a module nothing imports is absent from it rather than
    # present with 0. Ranking only its keys would drop those modules from the cutoff
    # entirely, and a repository of independent programs -- which has no keys at all --
    # would select nothing and be reported as having no module to describe.
    ranked = sorted(((path, fan_in.get(path, 0)) for path in known),
                    key=lambda kv: (-kv[1], kv[0]))

    reasons = {}
    for path, _count in ranked[:top]:
        reasons.setdefault(path, []).append("fan_in")
    # `known` is already restricted to files that define something, so an entry point
    # that defines nothing is skipped here too rather than added back.
    for entry in index.get("entry_points", ()):
        path = entry.get("path") if isinstance(entry, dict) else entry
        if path in set(known):
            reasons.setdefault(path, []).append("entry_point")
    return sorted(reasons), reasons, ranked


def warnings_for(index, ranked, selected):
    """The ways this selection is weaker than its size suggests."""
    notes = []
    if ranked and ranked[0][1] == 0:
        notes.append("no module in this repository is imported by another, so the fan-in "
                     "ranking carries no information -- the cutoff below is arbitrary. "
                     "Choose the units by hand and say in the document that you did.")
    entries = [e.get("path") if isinstance(e, dict) else e
               for e in index.get("entry_points", ())]
    files = len(index.get("files", ()))
    if files and len(entries) * 2 >= files:
        notes.append("the entry-point heuristic matched %d of %d scanned files; these are "
                     "candidates for a way in, not a list of them."
                     % (len(entries), files))
    return notes


def budget_note(selected, top):
    """Said when the selection is much larger than the cutoff that was asked for.

    Every entry point is added whatever the cutoff, which is right on a repository with
    two or three ways in and wrong on one where every file carries a `__main__` guard --
    a tree of standalone scripts, which is a shape this skill meets often. There `--top 8`
    selects sixty, and the number that decides the cost of the run is not the one that was
    typed. The proportion of entry points to files does not catch it: just under half of
    them can still be six times the cutoff.
    """
    if top and len(selected) > top * 2:
        return ("--top %d was asked for and %d unit(s) were selected: every entry point "
                "is added whatever the cutoff, and this repository has many. That is "
                "%.1fx the budget, so decide it deliberately -- raise --top and mean it, "
                "or name the units by hand." % (top, len(selected), len(selected) / float(top)))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--out", default=".docs-build/units.txt")
    parser.add_argument("--top", type=int, default=25,
                        help="how many modules to keep by fan-in (default 25)")
    args = parser.parse_args()

    if args.top < 0:
        return fail("--top must not be negative")
    if not os.path.isfile(args.index):
        return fail("no such index: %s" % args.index)
    try:
        with open(args.index, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError) as exc:
        return fail("cannot read %s: %s" % (args.index, exc))
    if index.get("schema_version") not in (2, 3):
        return fail("unsupported index schema_version %r" % index.get("schema_version"))

    paths, reasons, ranked = select(index, args.top)
    if not paths:
        return fail("the index holds no file to describe")

    directory = os.path.dirname(args.out)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(paths) + "\n")

    fan_in = index.get("fan_in") or {}
    for path in paths:
        print("%-4d %-12s %s" % (fan_in.get(path, 0), "+".join(reasons[path]), path))
    print("wrote %d unit(s) to %s -- top %d by fan-in plus every entry point"
          % (len(paths), args.out, args.top))
    for note in warnings_for(index, ranked, paths):
        print("WARN  %s" % note)
    overrun = budget_note(paths, args.top)
    if overrun:
        print("WARN  %s" % overrun)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("ERROR %s\n" % exc)
        sys.exit(3)
