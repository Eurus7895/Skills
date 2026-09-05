#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/check_prose.py
# Regenerate: python3 tools/materialize.py
"""Hold the rendered sentence to what the analysis behind it actually said.

    python3 scripts/check_prose.py .docs-build/doc.json \\
        --architecture .docs-build/architecture-analysis.json

Every check before this one asks whether a statement had evidence. None of them asks
whether the sentence a reader ends up seeing still says what that statement said, and
between `module-analysis.jsonl` and a rendered page sits a rewrite. A rewrite is where a
relationship gets promoted:

    `calls` becomes *owns*
    `imports` becomes *depends on*
    an `inferred` rationale loses its hedge and becomes the reason the boundary exists

None of those is caught by anything upstream. The claim is still verified, the statement
still cites its line, the page still passes the coverage checks -- and the reader is told
something nobody established.

Two deterministic rules, and they go a long way.

**A block may not use a stronger relationship verb than its sources carry.** Verbs are
ranked (below); a block citing statements is allowed the strongest verb any of those
statements uses, and a block citing only claims is allowed the ceiling of the claim kind.
An import proves a reference and nothing more, so a table built from `imports` claims may
say *imports* and may not say *depends on*.

**A block resting on an `inferred` reading must be hedged.** The status is in the model
and gets rendered away easily; a sentence that reads as observed fact is exactly what
`inferred` was recorded to prevent. The same holds for a rationale the architecture
analysis recorded as `unknown`: naming the open question is the answer, asserting it is
not.

Blocks carrying no citation at all are the generator's own framing -- the introductory
sentence above a table, the "nothing here, and why" line. They are not a rewrite of
anything and are reported as advisory rather than checked.

**What survives goes to a bounded model pass**, which this script does not run: the agent
does, and writes its verdicts to a JSONL that comes back through `--review`. With
`--require-review`, any queued block that has no verdict leaves the run
`review_required` -- the budget ran out before anything was decided, which is neither a
pass nor a defect in what was checked.

Standard library only. Reads; writes only where `--out` says to.

Exit codes: 0 ok, 1 findings, 2 input or schema error, 3 internal error.
"""

import argparse
import json
import os
import re
import sys

SUPPORTED_FORMAT = {1, 2}

PASSED, REVIEW_REQUIRED, FAILED = "passed", "review_required", "failed"

# Relationship verbs a page might use, by how much they claim. A higher rank asserts more
# about the relationship than a lower one, and the ladder is the whole of the first rule.
#
# It is deliberately short. A long list catches more promotions and also flags ordinary
# English -- "handles", "provides", "supports" say nothing precise about a relationship
# and would produce findings nobody can act on. These five ranks are the ones where the
# difference is a difference in what was established.
VERB_STRENGTH = (
    (1, ("references", "mentions", "names", "reads from")),
    (2, ("imports", "includes", "pulls in")),
    (3, ("uses", "consumes", "reads")),
    (4, ("calls", "invokes", "delegates to", "dispatches to")),
    (5, ("depends on", "requires", "relies on", "needs")),
    (6, ("owns", "manages", "controls", "drives", "orchestrates", "governs",
         "is responsible for")),
)

RANK_OF_VERB = {verb: rank for rank, verbs in VERB_STRENGTH for verb in verbs}

# What each claim kind licenses on its own. An `imports` edge proves a reference between
# two files and nothing about what either does with the other, so it stops at 2.
CLAIM_CEILING = {
    "imports": 2,
    "defines": 2,
    "contains": 2,
    "inherits": 4,
    "calls": 4,
    "responsibility": 6,
}

# A statement recorded as a reading, rendered as though it were a fact, is the second
# failure this file exists for. One of these has to survive the rewrite.
HEDGES = ("inferred", "not observed", "not recorded", "appears to", "seems to",
          "probably", "may ", "might ", "nobody answered", "does not say",
          "no reason", "unknown", "cannot be", "could not be")

STATEMENT_PROSE_STATUSES = ("declared", "observed", "inferred")


def fail(message, code=2):
    sys.stderr.write("FAIL  %s\n" % message)
    return code


def load_json(path, label):
    if not os.path.isfile(path):
        return None, "no such %s: %s" % (label, path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)


def verbs_in(text):
    """Every ranked verb the text uses, as (rank, verb), strongest first.

    Word boundaries on both ends: "callback" is not "call", and "downloads" is not
    "loads". A multi-word phrase is matched with its internal spacing collapsed, so a
    line break inside "depends on" does not hide it.
    """
    flat = " ".join(str(text).lower().split())
    found = []
    for verb, rank in RANK_OF_VERB.items():
        if re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(verb), flat):
            found.append((rank, verb))
    return sorted(found, reverse=True)


def strength(text):
    found = verbs_in(text)
    return found[0][0] if found else 0


def block_text(block):
    """Everything in a block a reader reads: prose, table cells, and column headers.

    The headers are not decoration. A table of rationales titled "The question nobody
    answered" is hedged by its own column, and leaving headers out of this made that
    table read as a set of assertions -- the exact false positive the hedge rule must
    not produce, on the one page written to be honest about not knowing.
    """
    parts = [block.get("text", "")]
    parts.extend(str(column) for column in block.get("columns", ()) or ())
    for row in block.get("rows", ()) or ():
        parts.extend(str(cell) for cell in row)
    return " ".join(p for p in parts if p)


def flatten(value):
    return " ".join(str(value).split())


def uncertain_texts(architecture=None, flows=None, operations=None):
    """Every sentence the analyses recorded as less than observed, flattened.

    The tables on the components, rationale, flows and operations pages are rendered
    mechanically and carry no claim or statement ref, so the verb rule above cannot reach
    them -- and it does not need to, because a mechanical render is not a rewrite. The
    hedge rule does need to reach them: a status is a single field, dropping it is a
    one-line change, and the sentence then reads as observed fact on the page.
    """
    texts = []

    def take(holder, status_key="status", text_key="text"):
        if isinstance(holder, dict) and holder.get(text_key) \
                and holder.get(status_key) in ("inferred", "unknown"):
            texts.append(flatten(holder[text_key]))

    for component in (architecture or {}).get("components", ()) or ():
        if isinstance(component, dict):
            take(component.get("rationale"))
    for flow in (flows or {}).get("flows", ()) or ():
        if not isinstance(flow, dict):
            continue
        take(flow.get("trigger"))
        take(flow.get("outcome"))
        for step in flow.get("steps", ()) or ():
            take(step)
        for entry in flow.get("unresolved", ()) or ():
            # A trace that stopped is never an observation, whatever it is labelled.
            if isinstance(entry, dict) and entry.get("reason"):
                texts.append(flatten(entry["reason"]))
    for procedure in (operations or {}).get("procedures", ()) or ():
        if not isinstance(procedure, dict):
            continue
        for step in procedure.get("steps", ()) or ():
            take(step)
    for requirement in (operations or {}).get("requirements", ()) or ():
        take(requirement)
    return [t for t in texts if t]


class Checker(object):
    def __init__(self, doc, uncertain=()):
        self.claims = {c.get("id"): c for c in doc.get("claims", ())}
        self.statements = {s.get("id"): s for s in doc.get("statements", ())}
        self.findings = []
        self.queue = []
        # Sentences the analyses recorded as inferred or unknown. Their text is a
        # reading or an open question, and a page stating one as an answer is the
        # seeded contradiction this rule is written for.
        self.uncertain = list(uncertain)

    def finding(self, code, message, subject=None, severity="error"):
        self.findings.append({"code": code, "severity": severity,
                              "subject": subject, "message": message})

    def allowance(self, block):
        """The strongest verb this block's sources license, and where that came from."""
        best, basis = 0, None
        for statement_id in block.get("analysis_refs", ()) or ():
            statement = self.statements.get(statement_id)
            if statement is None:
                continue
            # The statement's own words are the ceiling. This is the heart of it: the
            # page may restate what the analysis said and may not upgrade it.
            rank = strength(statement.get("text", ""))
            if rank >= best:
                best, basis = rank, "statement %s" % statement_id
        for claim_id in block.get("claim_refs", ()) or ():
            claim = self.claims.get(claim_id)
            if claim is None:
                continue
            rank = CLAIM_CEILING.get(claim.get("kind"), 0)
            if rank >= best:
                best, basis = rank, "a %s claim" % claim.get("kind")
        return best, basis

    def check_block(self, page_id, block):
        subject = block.get("id")
        text = block_text(block)
        if not text.strip():
            return
        lowered = text.lower()
        hedged = any(h in lowered for h in HEDGES)
        # This one runs on every block, cited or not: the mechanically rendered tables
        # are exactly where a dropped status would go unnoticed.
        for uncertain in self.uncertain:
            if uncertain.lower() in lowered and not hedged:
                self.finding("P004", "renders %r, which the analysis recorded as "
                             "inferred or unknown, with nothing marking it as such"
                             % (uncertain[:60] + ("..." if len(uncertain) > 60 else "")),
                             subject)
                break

        cited = list(block.get("analysis_refs", ()) or ()) \
            + list(block.get("claim_refs", ()) or ())
        if not cited:
            # Generator framing, not a rewrite. Named so a model pass can look, never
            # failed: there is no source to have overstated.
            self.finding("P005", "carries no citation, so nothing here can be compared "
                                 "with a source", subject, severity="advisory")
            return

        allowed, basis = self.allowance(block)
        used = verbs_in(text)
        for rank, verb in used:
            if rank > allowed:
                self.finding("P003", "says %r, which claims more than %s supports"
                             % (verb, basis or "its sources"), subject)
                break

        inferred = [s for s in (self.statements.get(i)
                                for i in block.get("analysis_refs", ()) or ())
                    if s and s.get("status") == "inferred"]
        if inferred and not hedged:
            self.finding("P004", "rests on an inferred reading (%s) and states it as "
                         "fact" % ", ".join(sorted(s["id"] for s in inferred)), subject)

        # What survives goes to the model pass: a reading, or a strong verb that the
        # sources happen to license. Both are places where only a person can tell a
        # restatement from an upgrade.
        if inferred or max([r for r, _ in used] or [0]) >= 5:
            self.queue.append({"page": page_id, "block": subject})

    def check(self, doc):
        for page in doc.get("pages", ()):
            for block in page.get("blocks", ()):
                if block.get("type") in ("prose", "table"):
                    self.check_block(page.get("id"), block)


def load_review(path):
    if not path:
        return None, None
    if not os.path.isfile(path):
        return None, "no such review file: %s" % path
    verdicts = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("block"):
                verdicts[row["block"]] = row
    return verdicts, None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("doc", help="doc.json")
    parser.add_argument("--architecture", help="architecture-analysis.json, so a "
                                               "rationale recorded as unknown cannot be "
                                               "asserted")
    parser.add_argument("--flows", help="flow-analysis.json, so an inferred trigger or "
                                        "outcome cannot be rendered as observed")
    parser.add_argument("--operations", help="operations-analysis.json, for the same "
                                             "reason")
    parser.add_argument("--review", help="JSONL of model-pass verdicts: "
                                         '{"block": "...", "verdict": "ok"|"overstated"}')
    parser.add_argument("--require-review", action="store_true",
                        help="a queued block with no verdict leaves the run "
                             "review_required rather than passed")
    parser.add_argument("--out", help="where to write the report; stdout either way")
    args = parser.parse_args()

    doc, error = load_json(args.doc, "document model")
    if error:
        return fail(error)
    if doc.get("format_version") not in SUPPORTED_FORMAT:
        return fail("unsupported doc format_version %r" % doc.get("format_version"))

    sources = {}
    for option, key, label in ((args.architecture, "architecture", "architecture "
                                                                   "analysis"),
                               (args.flows, "flows", "flow analysis"),
                               (args.operations, "operations", "operations analysis")):
        if not option:
            continue
        sources[key], error = load_json(option, label)
        if error:
            return fail(error)

    verdicts, error = load_review(args.review)
    if error:
        return fail(error)

    checker = Checker(doc, uncertain_texts(sources.get("architecture"),
                                           sources.get("flows"),
                                           sources.get("operations")))
    checker.check(doc)

    unreviewed = []
    if verdicts is not None:
        for entry in checker.queue:
            verdict = verdicts.get(entry["block"])
            if verdict is None:
                unreviewed.append(entry["block"])
            elif verdict.get("verdict") == "overstated":
                checker.finding("P007", "the model pass found this says more than its "
                                "source: %s" % verdict.get("note", "no note given"),
                                entry["block"])
        for block_id in sorted(verdicts):
            if not any(e["block"] == block_id for e in checker.queue):
                checker.finding("P006", "a verdict was supplied for a block that is not "
                                        "queued for review", block_id,
                                severity="advisory")
    elif args.require_review:
        unreviewed = [e["block"] for e in checker.queue]

    errors = [f for f in checker.findings if f["severity"] == "error"]
    if errors:
        status = FAILED
    elif args.require_review and unreviewed:
        # Nothing was learned about these. Reporting it as a pass would be the one thing
        # this status exists to prevent.
        status = REVIEW_REQUIRED
    else:
        status = PASSED

    report = {
        "schema_version": 1,
        "status": status,
        "passed": status == PASSED,
        "findings": checker.findings,
        "review_queue": checker.queue,
        "unreviewed": sorted(unreviewed),
        "coverage": {
            "blocks_checked": sum(1 for page in doc.get("pages", ())
                                  for b in page.get("blocks", ())
                                  if b.get("type") in ("prose", "table")),
            "blocks_uncited": sum(1 for f in checker.findings if f["code"] == "P005"),
            "queued": len(checker.queue),
            "reviewed": 0 if verdicts is None else len(verdicts),
        },
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if status == PASSED else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
