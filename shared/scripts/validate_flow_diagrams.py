#!/usr/bin/env python3
"""Validate generated PlantUML sequence diagrams against the flow analysis behind them.

    python3 scripts/validate_flow_diagrams.py docs/_diagrams \\
        --flows .docs-build/flow-analysis.json

The same job `validate_diagrams.py` does for class diagrams, for the sequence diagrams
`build_flow_diagrams.py` writes. The reason it is a separate step from generation is that
a `.puml` is a text file in the repository: it can be edited after it was generated, and
an arrow added by hand renders exactly like one that came from a verified call.

So the checks run in two directions, and both are needed:

    the metadata against the flow -- every message is a step the flow holds, in the
    order the flow holds it, between the entities the step names; every participant is
    an entity some step touches; every note repeats text the flow actually carries
    the drawn lines against the metadata -- what PlantUML will render is exactly what
    the metadata declares, so a hand-added arrow or lifeline is a finding rather than a
    silent addition to a document that otherwise passes

Findings use the diagram family, `G0xx`, shared with the class-diagram validator.

Standard library only. Reads; writes nothing.

Exit codes: 0 ok, 1 findings, 2 input or schema error, 3 internal error.
"""

import argparse
import hashlib
import json
import os
import re
import sys

SUPPORTED_MANIFEST_SCHEMA = {1}

DECLARATION = re.compile(r'^participant\s+"(?:[^"\\]|\\.)*"\s+as\s+(p_\w+)\s*$')
PARTICIPANT_SHAPED = re.compile(r"^(?:participant|actor|boundary|control|entity|"
                                r"collections|database|queue)\b")
MESSAGE = re.compile(r"^(p_\w+)\s*(->|-->|->>|<-)\s*(p_\w+)\s*:\s*(.*)$")
ARROW_SHAPED = re.compile(r"->|-->|->>|<-")
NOTE = re.compile(r"^note\s+over\s+(p_\w+)\s*:\s*(.*)$")
NOTE_SHAPED = re.compile(r"^(?:note|hnote|rnote)\b")


def fail(message, code=2):
    sys.stderr.write("FAIL  %s\n" % message)
    return code


def alias(identifier):
    readable = re.sub(r"[^A-Za-z0-9_]", "_", str(identifier)).strip("_")[-48:]
    suffix = hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:10]
    return "p_%s_%s" % (readable or "item", suffix)


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_json(path, label):
    if not os.path.isfile(path):
        return None, "no such %s: %s" % (label, path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read %s: %s" % (path, exc)


def parse_source(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return None, "cannot read %s: %s" % (path, exc)
    if text.count("@startuml") != 1 or text.count("@enduml") != 1:
        return None, "must contain exactly one @startuml and @enduml"
    if text.index("@startuml") > text.index("@enduml"):
        return None, "@enduml appears before @startuml"
    parsed = {"sequence": None, "participants": [], "messages": [], "notes": [],
              "declared": [], "drawn": [], "drawn_notes": [], "defects": []}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("'"):
            for marker, key in (("' @sequence ", "sequence"),
                                ("' @participant ", "participants"),
                                ("' @message ", "messages"), ("' @note ", "notes")):
                if not stripped.startswith(marker):
                    continue
                try:
                    value = json.loads(stripped[len(marker):])
                except ValueError as exc:
                    return None, ("line %d has malformed %s metadata: %s"
                                  % (number, key, exc))
                if key == "sequence":
                    if parsed[key] is not None:
                        return None, "contains duplicate sequence metadata"
                    parsed[key] = value
                else:
                    parsed[key].append(value)
            continue
        if PARTICIPANT_SHAPED.match(stripped):
            match = DECLARATION.match(stripped)
            if match is None:
                parsed["defects"].append(
                    "line %d declares a participant outside the generated form" % number)
            else:
                parsed["declared"].append(match.group(1))
        elif NOTE_SHAPED.match(stripped):
            match = NOTE.match(stripped)
            if match is None:
                parsed["defects"].append(
                    "line %d draws a note outside the generated form" % number)
            else:
                parsed["drawn_notes"].append(match.groups())
        elif ARROW_SHAPED.search(stripped):
            match = MESSAGE.match(stripped)
            if match is None:
                parsed["defects"].append(
                    "line %d draws a message outside the generated form" % number)
            else:
                parsed["drawn"].append(match.groups())
    if parsed["sequence"] is None:
        return None, "contains no sequence metadata"
    return parsed, None


def add(findings, code, message, view=None):
    findings.append({"code": code, "view": view, "message": message})


def participants_of(flow):
    order = []
    for step in flow.get("steps", ()):
        for end in (step.get("from"), step.get("to")):
            if end is not None and end not in order:
                order.append(end)
    return order


def note_texts(flow):
    """Every text a generated note is allowed to carry, already collapsed to one line."""
    allowed = set()
    trigger = flow.get("trigger") or {}
    if isinstance(trigger, dict) and trigger.get("text"):
        allowed.add(" ".join(str(trigger["text"]).split()))
    outcome = flow.get("outcome") or {}
    if isinstance(outcome, dict) and outcome.get("text"):
        allowed.add(" ".join(str(outcome["text"]).split()))
    for entry in flow.get("unresolved", ()) or ():
        if isinstance(entry, dict) and entry.get("reason"):
            allowed.add(" ".join(str(entry["reason"]).split()))
    return allowed


def validate_view(entry, parsed, flow, index_hash, findings):
    view = entry.get("flow")
    meta = parsed["sequence"]
    if meta != {key: entry.get(key) for key in
                ("schema_version", "flow", "index_hash", "flow_hash", "steps")}:
        add(findings, "G002", "PlantUML metadata does not match the manifest", view)
    if meta.get("index_hash") != index_hash:
        add(findings, "G002", "diagram was generated against a different scan", view)
    # The flow may have been edited after the diagram was drawn. Every check below would
    # still pass on the stale drawing, because they compare it to a flow it no longer
    # describes -- so this is the one that has to come first.
    if meta.get("flow_hash") != digest(flow):
        add(findings, "G002", "the flow changed after this diagram was generated", view)

    steps = list(flow.get("steps", ()))
    step_ids = [s.get("id") for s in steps]
    message_ids = [m.get("id") for m in parsed["messages"]]
    if message_ids != step_ids:
        # Order is the claim a sequence diagram makes. Comparing as lists rather than
        # sets is the whole point: the same arrows in another order is another flow.
        add(findings, "G001", "the messages are not the flow's steps in order", view)
    if message_ids != list(entry.get("messages", ())):
        add(findings, "G005", "PlantUML messages do not match the manifest", view)
    by_id = {s.get("id"): s for s in steps}
    for message in parsed["messages"]:
        step = by_id.get(message.get("id"))
        if step is None:
            add(findings, "G001", "draws a message the flow does not hold", view)
            continue
        if message.get("from") != step.get("from") or message.get("to") != step.get("to"):
            add(findings, "G003", "message %r changes its endpoints" % message.get("id"),
                view)

    expected = participants_of(flow)
    drawn_ids = [p.get("id") for p in parsed["participants"]]
    if len(drawn_ids) != len(set(drawn_ids)):
        add(findings, "G003", "contains duplicate participant metadata", view)
    if drawn_ids != expected:
        add(findings, "G001", "the participants are not the entities the steps touch, "
                              "in the order the flow reaches them", view)
    if sorted(drawn_ids) != sorted(entry.get("participants", ())):
        add(findings, "G005", "PlantUML participants do not match the manifest", view)

    allowed = note_texts(flow)
    for note in parsed["notes"]:
        if note.get("text") not in allowed:
            add(findings, "G001", "carries a note the flow does not say: %r"
                % note.get("text"), view)
        if note.get("anchor") not in expected:
            add(findings, "G003", "anchors a note to something the flow does not touch",
                view)

    # Everything above compares metadata to the flow. These compare what PlantUML will
    # actually draw to that same metadata: without them a lifeline or an arrow added by
    # hand renders in a document where every other check passed.
    for defect in parsed["defects"]:
        add(findings, "G006", defect, view)
    if parsed["declared"] != [alias(identifier) for identifier in drawn_ids]:
        add(findings, "G005", "the drawn participants are not the ones the metadata "
                              "declares", view)
    drawn = [(source, target) for source, arrow, target, _ in parsed["drawn"]]
    declared = [(alias(m.get("from")), alias(m.get("to"))) for m in parsed["messages"]]
    if drawn != declared:
        add(findings, "G005", "the drawn messages are not the ones the metadata declares",
            view)
    labels = [label for _, _, _, label in parsed["drawn"]]
    if labels != [m.get("label") for m in parsed["messages"]]:
        add(findings, "G005", "a drawn message is labelled with something other than "
                              "what the metadata declares", view)
    drawn_notes = [(anchor, text) for anchor, text in parsed["drawn_notes"]]
    declared_notes = [(alias(n.get("anchor")), n.get("text")) for n in parsed["notes"]]
    if drawn_notes != declared_notes:
        add(findings, "G005", "the drawn notes are not the ones the metadata declares",
            view)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory")
    parser.add_argument("--flows", required=True, help="flow-analysis.json")
    args = parser.parse_args()
    if not os.path.isdir(args.directory):
        return fail("not a directory: %s" % args.directory)
    doc, error = load_json(args.flows, "flow analysis")
    if error:
        return fail(error)
    manifest, error = load_json(
        os.path.join(args.directory, "flow-diagram-manifest.json"),
        "flow diagram manifest")
    if error:
        return fail(error)
    if manifest.get("schema_version") not in SUPPORTED_MANIFEST_SCHEMA:
        return fail("unsupported flow diagram manifest schema_version %r"
                    % manifest.get("schema_version"))
    index_hash = doc.get("index_hash")
    if manifest.get("index_hash") != index_hash:
        return fail("the manifest describes %s, the flow analysis is %s"
                    % (manifest.get("index_hash"), index_hash))

    flows = {f.get("id"): f for f in doc.get("flows", ()) or () if isinstance(f, dict)}
    findings, files = [], []
    for entry in manifest.get("views", ()):
        filename = entry.get("file")
        files.append(filename)
        flow = flows.get(entry.get("flow"))
        if flow is None:
            add(findings, "G001", "the manifest names a flow the analysis does not hold",
                entry.get("flow"))
            continue
        parsed, error = parse_source(os.path.join(args.directory, filename or ""))
        if error:
            add(findings, "G006", error, entry.get("flow"))
            continue
        validate_view(entry, parsed, flow, index_hash, findings)
    if len(files) != len(set(files)):
        add(findings, "G007", "manifest maps multiple flows to the same file")
    if not manifest.get("validated"):
        # The diagrams may be perfectly faithful to a flow analysis nothing checked.
        add(findings, "G007", "the diagrams were generated without a flow report, so "
                              "nothing vouches for the steps they draw")

    report = {"schema_version": 1, "passed": not findings, "findings": findings,
              "views": len(manifest.get("views", ())),
              "skipped": list(manifest.get("skipped", ()))}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
