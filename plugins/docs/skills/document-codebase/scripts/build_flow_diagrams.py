#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/build_flow_diagrams.py
# Regenerate: python3 tools/materialize.py
"""Generate deterministic PlantUML sequence diagrams from a validated flow analysis.

    python3 scripts/build_flow_diagrams.py --flows .docs-build/flow-analysis.json \\
        --report .docs-build/flow-report.json --out docs/_diagrams

`flow-analysis.json` is the claim and `.puml` is the reviewable artifact; rendering is
left to Sphinx and PlantUML, exactly as it is for the class diagrams.

A sequence diagram is the most persuasive thing this pipeline produces. Boxes and arrows
read as a fact about the running system in a way a paragraph never does, and a reader
will believe an arrow they would have questioned as a sentence. So every arrow here comes
from a step that `validate_flows.py` accepted -- which means a call `verify_doc.py` read
at its call site -- and every arrow is labelled with the file and line it was read at.
Nothing is drawn that the flow does not hold, and nothing the flow holds is left out.

`--report` is how that is enforced across the two files: given a report from
`validate_flows.py`, a flow it refused is skipped rather than drawn. Without one, every
flow in the file is drawn and the manifest records that nothing vouched for them.

The metadata comments (`' @sequence`, `' @participant`, `' @message`, `' @note`) are what
`validate_flow_diagrams.py` reads back. They are the diagram's own account of itself, and
checking them against both the flow and the drawn lines is what stops a hand-edited arrow
from riding along inside a validated document.

Standard library only. Writes only into --out.

Exit codes: 0 ok, 1 nothing could be drawn, 2 input or schema error, 3 internal error.
"""

import argparse
import hashlib
import json
import os
import re
import sys

SUPPORTED_FLOW_VERSION = {1}
MANIFEST_SCHEMA = 1


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


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def alias(identifier):
    """The participant alias derived from an entity id. Kept in step with the validator."""
    readable = re.sub(r"[^A-Za-z0-9_]", "_", str(identifier)).strip("_")[-48:]
    suffix = hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:10]
    return "p_%s_%s" % (readable or "item", suffix)


def slug(value):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(value)).strip("-").lower() or "flow"


def quote(value):
    value = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % value.replace("\r", " ").replace("\n", " ")


def one_line(value):
    """Note and label text on a single line: PlantUML gives a newline its own meaning."""
    return " ".join(str(value).split())


def label_of(entity):
    """`symbol:src/pipeline/entry.py:main` -> `entry.main`; a module keeps its basename."""
    kind, _, rest = str(entity).partition(":")
    if kind == "module":
        return os.path.basename(rest) or rest
    path, _, name = rest.rpartition(":")
    stem = os.path.splitext(os.path.basename(path))[0]
    return "%s.%s" % (stem, name) if stem else name


def cite(evidence):
    for item in evidence or ():
        if isinstance(item, dict) and item.get("path") and item.get("line_start"):
            return "%s:%s" % (item["path"], item["line_start"])
    return ""


def participants_of(flow):
    """Entities in the order the flow first reaches them -- the lifeline order."""
    order = []
    for step in flow.get("steps", ()):
        for end in (step.get("from"), step.get("to")):
            if end is not None and end not in order:
                order.append(end)
    return order


def render(flow, index_hash):
    order = participants_of(flow)
    steps = list(flow.get("steps", ()))
    # A trigger is what happens before the first arrow and an outcome is what is left
    # after the last, so they are emitted on either side of the messages. Collecting
    # them into one list and appending it at the end drew the trigger at the bottom of
    # the diagram, under the call it starts.
    before, after = [], []
    trigger = flow.get("trigger") or {}
    if isinstance(trigger, dict) and trigger.get("text"):
        before.append({"kind": "trigger", "anchor": order[0] if order else None,
                       "text": one_line(trigger["text"]),
                       "status": trigger.get("status")})
    outcome = flow.get("outcome") or {}
    if isinstance(outcome, dict) and outcome.get("text"):
        after.append({"kind": "outcome", "anchor": order[-1] if order else None,
                      "text": one_line(outcome["text"]),
                      "status": outcome.get("status")})
    for entry in flow.get("unresolved", ()) or ():
        if isinstance(entry, dict) and entry.get("reason"):
            after.append({"kind": "unresolved", "anchor": order[-1] if order else None,
                          "text": one_line(entry["reason"]), "status": "unknown"})
    notes = before + after

    meta = {"schema_version": 1, "flow": flow.get("id"), "index_hash": index_hash,
            "flow_hash": digest(flow), "steps": len(steps)}
    lines = ["@startuml",
             "' Generated from flow-analysis.json; do not edit by hand.",
             "autonumber", "skinparam sequenceMessageAlign left",
             "' @sequence %s" % json.dumps(meta, sort_keys=True, separators=(",", ":"))]
    for entity in order:
        lines.append("participant %s as %s" % (quote(label_of(entity)), alias(entity)))
        lines.append("' @participant %s" % json.dumps(
            {"id": entity, "label": label_of(entity)},
            sort_keys=True, separators=(",", ":")))
    if not order:
        lines.append('note over "empty" : This flow has no step.')

    def emit_notes(group):
        for note in group:
            if note["anchor"] is None:
                continue
            lines.append("note over %s : %s" % (alias(note["anchor"]), note["text"]))
            lines.append("' @note %s" % json.dumps(note, sort_keys=True,
                                                   separators=(",", ":")))

    emit_notes(before)
    for step in steps:
        where = cite(step.get("evidence"))
        lines.append("%s -> %s : %s" % (alias(step.get("from")), alias(step.get("to")),
                                        one_line(where or step.get("id", ""))))
        lines.append("' @message %s" % json.dumps(
            {"id": step.get("id"), "from": step.get("from"), "to": step.get("to"),
             "label": one_line(where or step.get("id", ""))},
            sort_keys=True, separators=(",", ":")))
    emit_notes(after)
    lines.extend(["@enduml", ""])
    return "\n".join(lines), meta, order, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--flows", required=True, help="flow-analysis.json")
    parser.add_argument("--report", help="the report from validate_flows.py, so a flow "
                                         "it refused is not drawn")
    parser.add_argument("--out", default="docs/_diagrams")
    args = parser.parse_args()

    doc, error = load_json(args.flows, "flow analysis")
    if error:
        return fail(error)
    if not isinstance(doc, dict):
        return fail("%s does not contain a JSON object" % args.flows)
    if doc.get("flow_version", 1) not in SUPPORTED_FLOW_VERSION:
        return fail("unsupported flow_version %r" % doc.get("flow_version"))
    index_hash = doc.get("index_hash")
    if not index_hash:
        return fail("the flow analysis carries no index_hash")

    accepted, accepted_hashes = None, {}
    if args.report:
        report, error = load_json(args.report, "flow report")
        if error:
            return fail(error)
        if report.get("index_hash") != index_hash:
            return fail("the report describes %s, the flow analysis is %s"
                        % (report.get("index_hash"), index_hash))
        accepted = set(report.get("accepted", ()))
        accepted_hashes = report.get("flow_hashes") or {}
        if accepted and not accepted_hashes:
            # An older report, from before the hashes existed. Its ids alone cannot say
            # which version of a flow was accepted, and drawing on that basis is exactly
            # what the hashes are for.
            return fail("the report carries no flow_hashes, so it cannot say which "
                        "version of each flow it accepted -- rerun validate_flows.py")

    os.makedirs(args.out, exist_ok=True)
    entries, skipped = [], []
    for flow in doc.get("flows", ()) or ():
        if not isinstance(flow, dict) or not flow.get("id"):
            continue
        if accepted is not None and flow["id"] not in accepted:
            skipped.append(flow["id"])
            continue
        if accepted is not None and accepted_hashes.get(flow["id"]) != digest(flow):
            # Same id, same scan, different flow: the file was edited after it was
            # validated. Refusing here is the only place that catches it -- the diagram
            # validator compares the drawing against the edited flow and would agree.
            return fail("%s was edited after the report was written; rerun "
                        "validate_flows.py" % flow["id"])
        source, meta, order, notes = render(flow, index_hash)
        filename = "flow-%s.puml" % slug(flow["id"].split(":", 1)[-1])
        with open(os.path.join(args.out, filename), "w", encoding="utf-8") as fh:
            fh.write(source)
        entries.append(dict(meta, file=filename, participants=list(order),
                            messages=[s.get("id") for s in flow.get("steps", ())],
                            notes=notes))
        print("%s: %d participant(s), %d message(s)"
              % (flow["id"], len(order), len(entries[-1]["messages"])))

    manifest = {"schema_version": MANIFEST_SCHEMA, "index_hash": index_hash,
                # Whether anything vouched for these flows. A reader of the manifest
                # alone would otherwise have no way to tell a checked diagram from one
                # drawn straight out of an unvalidated file.
                "validated": accepted is not None,
                "skipped": sorted(skipped), "views": entries}
    with open(os.path.join(args.out, "flow-diagram-manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    if skipped:
        print("skipped %d refused flow(s): %s" % (len(skipped), ", ".join(sorted(skipped))))
    print("wrote %d sequence diagram(s) to %s" % (len(entries), args.out))
    if not entries:
        # Not an error: a repository with no traceable flow is a real answer, and the
        # document says so in prose. But the caller should not think a diagram exists.
        sys.stderr.write("NOTE  no flow was drawn\n")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
