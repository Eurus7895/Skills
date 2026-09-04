#!/usr/bin/env python3
"""Hold `flow-analysis.json` to its schema, its evidence, and to being a chain of calls.

    python3 scripts/validate_flows.py .docs-build/flow-analysis.json \\
        --index .docs-build/structure.json --claims .docs-build/claims.verified.jsonl

A flow is the sentence a reader most wants and the one a documentation generator is most
likely to invent: *the request arrives at the handler, which records the order, which
writes it to the store*. Three hops, each of which either happens in the code or does not.

The rule this file exists to enforce is that each hop is a call **verified at its call
site** -- a claim `verify_doc.py` decided by opening the file, finding an `ast.Call` on
the cited line, and confirming the name was bound by an import from the file the callee
lives in. Nothing else may become a step. An import edge would give a much fuller picture
much faster, and it is a different, weaker statement: "these two files reference each
other" is not what a reader takes "the request passes through here" to mean.

So the checks are:

    every step names entities the index knows, and cites a claim that is a verified call
    between exactly those two entities
    consecutive steps join up -- what step n reaches is where step n+1 starts, or the
    flow is a bag of calls with an order imposed on it
    a flow with a broken step is refused rather than trimmed to the part that held
    a repository with no traceable flow says so, and that is a complete answer

That last one matters more than it looks. `absent` with a reason is a result; an empty
`flows` list with nothing said about it is a generator that gave up quietly, and the two
have to be told apart before anything downstream can report coverage honestly.

Statuses are the statement vocabulary: `declared`, `observed`, `inferred`, `unknown`.

Standard library only. Reads; writes only where `--out` says to.

Exit codes: 0 ok, 1 findings, 2 input or schema error, 3 internal error.
"""

import argparse
import json
import os
import sys

SUPPORTED_FLOW_VERSION = {1}

STATUSES = ("declared", "observed", "inferred", "unknown")

# How a flow starts. `call` is the honest answer for a chain that begins inside the
# library with no entry point of its own -- a caller has to exist, but the repository
# does not say who it is.
TRIGGER_KINDS = ("http", "cli", "schedule", "event", "message", "call", "unknown")

REQUIRED_FLOW = ("id", "name", "trigger", "status", "steps")
REQUIRED_STEP = ("id", "from", "to", "text", "status")
REQUIRED_TRIGGER = ("kind", "text", "status")

ENTITY_KINDS = ("module", "symbol", "class", "method")


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


def parse_entity(entity):
    """'method:src/a.py:Repo.get' -> ('method', 'src/a.py', 'Repo.get'), else None."""
    if not isinstance(entity, str) or ":" not in entity:
        return None
    kind, rest = entity.split(":", 1)
    if kind == "module":
        return (kind, rest, None) if rest else None
    if kind in ENTITY_KINDS:
        if ":" not in rest:
            return None
        path, name = rest.rsplit(":", 1)
        return (kind, path, name) if path and name else None
    return None


def load_claims(path):
    """Verified `calls` claims by id, or `(None, None)` when none were supplied.

    A mistyped `--claims` must not read as "there is nothing to check against": that
    would turn the one check this file exists for into advice and exit 0.
    """
    if not path:
        return None, None
    if not os.path.isfile(path):
        return None, "no such claims file: %s" % path
    claims = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id"):
                claims[row["id"]] = row
    return claims, None


class Checker(object):
    def __init__(self, index, claims=None):
        self.by_path = {record["path"]: record for record in index.get("files", ())}
        self.assets = {record["path"]: record for record in index.get("assets", ())}
        # None means "no claims file was supplied", which is not the same as "it held no
        # verified call". The first cannot be checked; the second is a finding.
        self.claims = claims
        self.findings = []

    def finding(self, code, message, subject=None, severity="error"):
        self.findings.append({"code": code, "severity": severity,
                              "subject": subject, "message": message})

    def check_evidence(self, subject, evidence, required=True):
        if not isinstance(evidence, list) or not evidence:
            if required:
                self.finding("F011", "carries no evidence", subject)
            return not required
        ok = True
        for item in evidence:
            if not isinstance(item, dict) or "path" not in item:
                self.finding("F011", "an evidence record has no path", subject)
                ok = False
                continue
            record = self.by_path.get(item["path"])
            asset = None if record is not None else self.assets.get(item["path"])
            if record is None and asset is None:
                self.finding("F007", "evidence names %r, which the index does not hold"
                             % item["path"], subject)
                ok = False
                continue
            length = record.get("loc", 0) if record is not None else asset.get("lines", 0)
            start = item.get("line_start")
            end = item.get("line_end", start)
            if not isinstance(start, int) or not isinstance(end, int) \
                    or start < 1 or end < start or end > length:
                self.finding("F007", "evidence cites lines %r-%r of a %d-line file"
                             % (start, end, length), subject)
                ok = False
        return ok

    def check_entity(self, subject, label, entity):
        """The entity parses and names a file the index holds. Returns its path or None."""
        parsed = parse_entity(entity)
        if parsed is None:
            self.finding("F002", "%s is %r, which is not an entity id" % (label, entity),
                         subject)
            return None
        if parsed[1] not in self.by_path:
            self.finding("F003", "%s names %r, which the index does not know"
                         % (label, parsed[1]), subject)
            return None
        return parsed[1]

    def check_step_claims(self, subject, step):
        """The hop is a call the verifier confirmed at its call site, or it is not a hop.

        Matching the claim's endpoints against the step's is the part that does the work.
        A step may otherwise cite any verified call in the repository and inherit its
        standing -- the id would prove a call happened somewhere, not that *this* hop did.
        """
        ids = step.get("claim_ids")
        if not isinstance(ids, list) or not ids:
            self.finding("F006", "cites no claim, so nothing says this call was read at "
                                 "its call site", subject)
            return False
        if self.claims is None:
            self.finding("F006", "cites claims, but no claims file was given to check "
                                 "them against", subject, severity="advisory")
            return False
        for claim_id in ids:
            claim = self.claims.get(claim_id)
            if claim is None:
                self.finding("F006", "cites claim %r, which the claims file does not "
                             "contain" % claim_id, subject)
                return False
            if claim.get("kind") != "calls":
                self.finding("F006", "cites claim %r, which is a %r claim -- a step is a "
                             "call or it is not a step"
                             % (claim_id, claim.get("kind")), subject)
                return False
            if claim.get("status") != "verified":
                self.finding("F006", "cites claim %r, which the verifier left as %r"
                             % (claim_id, claim.get("status")), subject)
                return False
            if claim.get("subject") != step.get("from") \
                    or claim.get("object") != step.get("to"):
                self.finding("F006", "cites claim %r, which is a call from %r to %r -- "
                             "not this hop" % (claim_id, claim.get("subject"),
                                               claim.get("object")), subject)
                return False
        return True

    def check_flow(self, flow, ids):
        subject = flow.get("id") if isinstance(flow, dict) else repr(flow)
        if not isinstance(flow, dict):
            self.finding("F002", "a flow is not an object", subject)
            return False
        missing = [f for f in REQUIRED_FLOW if f not in flow]
        if missing:
            self.finding("F002", "missing %s" % ", ".join(missing), subject)
            return False
        if flow["id"] in ids:
            self.finding("F005", "id used more than once", subject)
        ids.add(flow["id"])
        intact = True
        if flow["status"] not in STATUSES:
            self.finding("F012", "status %r is not one this schema defines"
                         % flow["status"], subject)
            intact = False

        trigger = flow["trigger"]
        if not isinstance(trigger, dict):
            self.finding("F002", "trigger is not an object", subject)
            intact = False
        else:
            missing = [f for f in REQUIRED_TRIGGER if f not in trigger]
            if missing:
                self.finding("F002", "trigger is missing %s" % ", ".join(missing), subject)
                intact = False
            else:
                if trigger["kind"] not in TRIGGER_KINDS:
                    self.finding("F012", "trigger kind %r is not one this schema defines"
                                 % trigger["kind"], subject)
                    intact = False
                if trigger["status"] not in STATUSES:
                    self.finding("F012", "trigger status %r is not one this schema "
                                 "defines" % trigger["status"], subject)
                    intact = False
                # An `unknown` trigger is the honest answer for a chain whose caller the
                # repository never names, and there is nothing to cite for it.
                if trigger["status"] != "unknown":
                    intact &= self.check_evidence("%s trigger" % subject,
                                                  trigger.get("evidence"))

        steps = flow["steps"]
        if not isinstance(steps, list) or not steps:
            # A flow with no steps is a title. The absent case has its own field, and
            # using it is how a generator says "nothing traceable here" on purpose.
            self.finding("F010", "has no step", subject)
            return False

        previous = None
        for position, step in enumerate(steps):
            if not isinstance(step, dict):
                self.finding("F002", "step %d is not an object" % position, subject)
                intact = False
                continue
            missing = [f for f in REQUIRED_STEP if f not in step]
            if missing:
                self.finding("F002", "step %d is missing %s"
                             % (position, ", ".join(missing)), subject)
                intact = False
                continue
            step_subject = "%s / %s" % (subject, step["id"])
            if step["id"] in ids:
                self.finding("F005", "id used more than once", step_subject)
            ids.add(step["id"])
            if step["status"] not in STATUSES:
                self.finding("F012", "status %r is not one this schema defines"
                             % step["status"], step_subject)
                intact = False
            source = self.check_entity(step_subject, "from", step.get("from"))
            target = self.check_entity(step_subject, "to", step.get("to"))
            intact &= source is not None and target is not None
            if step.get("evidence") is not None:
                intact &= self.check_evidence(step_subject, step.get("evidence"))
            intact &= self.check_step_claims(step_subject, step)
            # What step n reached is where step n+1 starts. Without this a flow is a set
            # of calls with an order imposed on it, and the order is the whole claim.
            if previous is not None and source is not None and previous != source:
                self.finding("F004", "starts in %s, but the step before it reached %s"
                             % (source, previous), step_subject)
                intact = False
            if target is not None:
                previous = target

        outcome = flow.get("outcome")
        if isinstance(outcome, dict):
            if outcome.get("status") not in STATUSES:
                self.finding("F012", "outcome status %r is not one this schema defines"
                             % outcome.get("status"), subject)
                intact = False
            elif outcome["status"] != "unknown":
                intact &= self.check_evidence("%s outcome" % subject,
                                              outcome.get("evidence"))
        elif outcome is not None:
            self.finding("F002", "outcome is not an object", subject)
            intact = False

        for entry in flow.get("unresolved", ()) or ():
            if not isinstance(entry, dict) or not entry.get("reason"):
                self.finding("F002", "an unresolved entry has no reason", subject)
                intact = False
        return bool(intact)

    def check(self, doc):
        ids, refused, accepted = set(), [], []
        flows = doc.get("flows")
        if flows is None:
            flows = []
        if not isinstance(flows, list):
            self.finding("F002", "flows is not a list")
            flows = []

        for flow in flows:
            if self.check_flow(flow, ids):
                accepted.append(flow.get("id") if isinstance(flow, dict) else None)
            else:
                refused.append(flow.get("id") if isinstance(flow, dict) else None)

        absent = doc.get("absent")
        if not flows:
            if not isinstance(absent, dict) or not absent.get("reason"):
                # Silence and "there is nothing here" look identical downstream, and only
                # one of them is an answer.
                self.finding("F013", "names no flow and does not say why -- an empty "
                                     "flows list needs an absent reason")
        elif absent is not None:
            self.finding("F013", "declares flows and an absent reason at the same time")
        return accepted, refused


def report_of(doc, checker, accepted, refused):
    flows = [f for f in doc.get("flows", ()) or () if isinstance(f, dict)]
    steps = [s for f in flows for s in (f.get("steps") or ()) if isinstance(s, dict)]
    errors = [f for f in checker.findings if f["severity"] == "error"]
    return {
        "flow_version": doc.get("flow_version"),
        "index_hash": doc.get("index_hash"),
        "passed": not errors,
        "findings": checker.findings,
        # A flow is accepted whole or refused whole. Reporting the two lists rather than
        # a count keeps the page builder from rendering the half that happened to hold.
        "accepted": [f for f in accepted if f is not None],
        "refused": [f for f in refused if f is not None],
        "absent": bool(isinstance(doc.get("absent"), dict)
                       and doc["absent"].get("reason")),
        "coverage": {
            "flows": len(flows),
            "flows_accepted": len(accepted),
            "flows_refused": len(refused),
            "steps": len(steps),
            "steps_with_claims": sum(1 for s in steps if s.get("claim_ids")),
            "unresolved": sum(len(f.get("unresolved") or ()) for f in flows),
            "triggers_with_evidence": sum(
                1 for f in flows
                if isinstance(f.get("trigger"), dict) and f["trigger"].get("evidence")),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("flows", help="flow-analysis.json")
    parser.add_argument("--index", required=True, help="path to structure.json")
    parser.add_argument("--claims", help="claims.verified.jsonl, so a step's call can be "
                                         "checked rather than trusted")
    parser.add_argument("--out", help="where to write the report; stdout either way")
    args = parser.parse_args()

    index, error = load_json(args.index, "index")
    if error:
        return fail(error)
    if index.get("schema_version") not in (2, 3):
        return fail("unsupported index schema_version %r" % index.get("schema_version"))

    doc, error = load_json(args.flows, "flow analysis")
    if error:
        return fail(error)
    if not isinstance(doc, dict):
        return fail("%s does not contain a JSON object" % args.flows)
    version = doc.get("flow_version", 1)
    if version not in SUPPORTED_FLOW_VERSION:
        return fail("unsupported flow_version %r" % version)

    stated = doc.get("index_hash")
    if not stated:
        return fail("the analysis carries no index_hash, so which scan it describes is "
                    "unknown")
    if stated != index.get("index_hash"):
        return fail("the analysis was written against %s, the index is %s -- rerun the "
                    "analysis or rescan" % (stated, index.get("index_hash")))

    claims, error = load_claims(args.claims)
    if error:
        return fail(error)

    checker = Checker(index, claims)
    accepted, refused = checker.check(doc)
    report = report_of(doc, checker, accepted, refused)

    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
