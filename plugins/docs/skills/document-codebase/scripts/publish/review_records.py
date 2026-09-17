#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/publish/review_records.py
# Regenerate: python3 tools/materialize.py
"""What a review is *about*, and how to tell when it stopped being about it.

A review row is an approval, so the only question that matters is whether it still
applies. Three things are kept apart here, because collapsing them is what let one
`confirmed` flag stand for all three:

    content review   did a reviewer accept this wording?
    freshness        is that verdict still about what the document now says?
    completeness     does the document cover the scope that was promised?

A section can be reviewed and stale. It can be reviewed, fresh, and still missing half
of what its question asked for. Those are three different reports to a reader and three
different pieces of work, and a single boolean could express none of them.

**Freshness is decided by hashes, not by trust.** A row names the content it judged and
the inputs it judged that content against; when any of them differs from what is on disk
now, the verdict is stale and says so. Nothing has to remember to invalidate anything.

Standard library only. No I/O: callers own the files.
"""

import hashlib
import json

REVIEW_VERSION = 2

VERDICTS = ("confirmed", "changes_requested", "unresolved")
REVIEW_MODES = ("independent", "self_review")
SEVERITIES = ("blocking", "major", "minor")
FINDING_STATES = ("open", "resolved", "withdrawn")

# Freshness inputs, in the order a report should mention them. Each is a hash the row
# carries and the run recomputes; `content` is the section itself, the rest are what the
# section was written from.
BOUND_INPUTS = ("content_hash", "index_hash", "scope_hash", "analysis_hash")

REQUIRED = ("review_version", "review_id", "target_id", "draft_revision", "verdict",
            "review_mode", "reviewer", "content_hash")


def content_hash(block):
    """The stable identity of one composed section.

    Over heading, body and evidence -- what a reader sees and what it rests on -- and
    **never** over the review result, a timestamp or a rendered revision number. Hashing
    the verdict into the thing the verdict is about is a cycle: approving a section would
    change its hash and immediately stale the approval that just landed.

    Evidence is normalised and sorted, so reordering two citations is not an edit while
    adding one is.
    """
    payload = {
        "heading": (block.get("heading") or "").strip(),
        "body": (block.get("body") or block.get("text") or "").strip(),
        "evidence": sorted(
            "%s:%s-%s" % (item.get("path"), item.get("line_start"), item.get("line_end"))
            for item in block.get("evidence", ()) or ()),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def digest_of(value):
    """A hash for any other bound input -- an analysis file, a scope record."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def malformed(row):
    """Why this row cannot be read as a review, or None.

    A row that cannot be read is refused rather than ignored: a review file whose bad
    rows are silently dropped reports fewer approvals than it has, and the run reads that
    as work still to do instead of as a file to fix.
    """
    if not isinstance(row, dict):
        return "a review row must be an object"
    if row.get("review_version") != REVIEW_VERSION:
        # v1 rows were `{"page": ..., "block": ..., "verdict": "ok"}` -- a block id and a
        # word, bound to nothing. They name no content, so nothing can establish what
        # they approved; they migrate to pending, never to an approval.
        return ("review_version %r is not %d; a row that names no content hash cannot "
                "say what it approved" % (row.get("review_version"), REVIEW_VERSION))
    missing = [field for field in REQUIRED if not row.get(field)]
    if missing:
        return "missing %s" % ", ".join(missing)
    if row["verdict"] not in VERDICTS:
        return "verdict %r is not one of %s" % (row["verdict"], ", ".join(VERDICTS))
    if row["review_mode"] not in REVIEW_MODES:
        return ("review_mode %r is not one of %s -- a sequential pass reports "
                "`self_review` and may not claim independence it did not have"
                % (row["review_mode"], ", ".join(REVIEW_MODES)))
    for finding in row.get("findings", ()) or ():
        if not isinstance(finding, dict):
            return "a finding must be an object"
        absent = [f for f in ("finding_id", "severity", "location", "why", "requested")
                  if not finding.get(f)]
        if absent:
            return "finding %r is missing %s" % (finding.get("finding_id", "<no id>"),
                                                 ", ".join(absent))
        if finding["severity"] not in SEVERITIES:
            return "finding %s has severity %r" % (finding["finding_id"],
                                                   finding["severity"])
        if finding.get("state", "open") not in FINDING_STATES:
            return "finding %s has state %r" % (finding["finding_id"],
                                                finding.get("state"))
    # A verdict of `confirmed` alongside an unresolved blocking finding is the row
    # disagreeing with itself, and reading either half as the answer is a guess.
    blocking = [f for f in row.get("findings", ()) or ()
                if f.get("severity") == "blocking" and f.get("state", "open") == "open"]
    if row["verdict"] == "confirmed" and blocking:
        return ("verdict is `confirmed` while %d blocking finding(s) are open: %s"
                % (len(blocking), ", ".join(f["finding_id"] for f in blocking[:3])))
    return None


def staleness(row, current):
    """Which bound inputs have moved since the review, in report order.

    `current` maps an input name to the hash the run computes now. An input the run
    cannot compute is not evidence of freshness and is skipped rather than assumed equal
    -- the conservative reading, because the alternative silently revives a stale
    approval whenever a hash happens to be unavailable.
    """
    moved = []
    for name in BOUND_INPUTS:
        recorded, now = row.get(name), current.get(name)
        if recorded and now and recorded != now:
            moved.append(name)
    return moved


def applies(row, current):
    """Whether this row is a usable approval of what the document now says."""
    return (malformed(row) is None
            and row["verdict"] == "confirmed"
            and not staleness(row, current))
