#!/usr/bin/env python3
"""The review and scope records keep content review, freshness and completeness apart."""
import sys

from component_scripts import component_paths
sys.path[:0] = component_paths()
import review_records as rr
import scope_record as sr

failures = []


def check(label, ok, detail=""):
    print("%s   %s" % ("ok " if ok else "FAIL", label))
    if not ok:
        failures.append("%s: %s" % (label, detail))


SECTION = {"heading": "Configuration", "body": "OrderLog reads three settings.",
           "evidence": [{"path": "app.py", "line_start": 4, "line_end": 4},
                        {"path": "app.py", "line_start": 6, "line_end": 6}]}


def review(**over):
    row = {"review_version": 2, "review_id": "rev-1", "target_id": "section:usage:1",
           "draft_revision": "rev-0001", "verdict": "confirmed",
           "review_mode": "independent", "reviewer": "analyst-2",
           "content_hash": rr.content_hash(SECTION), "index_hash": "sha256:idx",
           "scope_hash": "sha256:scope", "findings": []}
    row.update(over)
    return row


# --- the acceptance criterion: three states, not one flag -------------------------
now = {"content_hash": rr.content_hash(SECTION), "index_hash": "sha256:idx",
       "scope_hash": "sha256:scope"}

row = review()
check("reviewed, fresh, and usable as an approval", rr.applies(row, now))

edited = dict(SECTION, body="OrderLog reads four settings.")
check("reviewed but stale: the body changed under the same target id",
      rr.staleness(row, dict(now, content_hash=rr.content_hash(edited))) == ["content_hash"]
      and not rr.applies(row, dict(now, content_hash=rr.content_hash(edited))))

check("reviewed but stale: the source index moved",
      rr.staleness(row, dict(now, index_hash="sha256:rescanned")) == ["index_hash"])

check("reviewed but stale: the scope changed",
      rr.staleness(row, dict(now, scope_hash="sha256:wider")) == ["scope_hash"])

# Completeness is a property of the answer, not of the review — a section can be
# accepted as written and still not cover what its question asked for. The review
# record has no opinion on it, which is the separation working.
check("a fresh approval says nothing about completeness",
      "completeness" not in row and rr.applies(row, now))

# --- the hash rule ----------------------------------------------------------------
check("reordering evidence is not an edit",
      rr.content_hash(SECTION) == rr.content_hash(
          dict(SECTION, evidence=list(reversed(SECTION["evidence"])))))
check("adding evidence is an edit",
      rr.content_hash(SECTION) != rr.content_hash(
          dict(SECTION, evidence=SECTION["evidence"] + [
              {"path": "app.py", "line_start": 9, "line_end": 9}])))
# The cycle this avoids: if the verdict were hashed in, approving a section would
# change its hash and instantly stale the approval that had just landed.
check("the verdict is not part of the content identity",
      rr.content_hash(dict(SECTION, verdict="confirmed", reviewed_at="2026-01-01"))
      == rr.content_hash(SECTION))

# --- rows that cannot be read are refused, not dropped -----------------------------
check("a v1 row names no content and cannot approve anything",
      rr.malformed({"page": "usage", "block": "section:usage:1", "verdict": "ok"})
      is not None)
check("a row with no content hash is malformed",
      rr.malformed(review(content_hash=None)) is not None)
check("confirmed while a blocking finding is open is self-contradictory",
      rr.malformed(review(findings=[{"finding_id": "f1", "severity": "blocking",
                                     "location": "section:usage:1", "why": "wrong",
                                     "requested": "fix", "state": "open"}])) is not None)
check("the same finding resolved no longer contradicts the verdict",
      rr.malformed(review(findings=[{"finding_id": "f1", "severity": "blocking",
                                     "location": "section:usage:1", "why": "wrong",
                                     "requested": "fix", "state": "resolved"}])) is None)
check("a sequential pass cannot claim independence",
      rr.malformed(review(review_mode="pretend_independent")) is not None)
check("self_review is a legal mode, honestly labelled",
      rr.malformed(review(review_mode="self_review")) is None)

# An input the run cannot compute is not evidence of freshness.
check("an uncomputable input is skipped, never assumed equal",
      rr.staleness(row, {"content_hash": rr.content_hash(SECTION)}) == [])

# --- scope ------------------------------------------------------------------------
def scope(**over):
    base = {"scope_version": 1, "index_hash": "sha256:idx",
            "product_roots": ["src"], "required_topics": ["configuration"],
            "files": [
                {"path": "src/app.py", "disposition": "product", "reading": "analyzed"},
                {"path": "src/rare.py", "disposition": "product", "reading": "unread"},
                {"path": "tests/test_app.py", "disposition": "test", "reading": "excluded",
                 "reason": "pytest suite under tests/"}]}
    base.update(over)
    return base


check("a well-formed scope reads", sr.malformed(scope()) is None)
check("an exclusion with no reason is refused",
      sr.malformed(scope(files=[{"path": "src/contest.py", "disposition": "test",
                                 "reading": "excluded"}])) is not None)

cover = sr.coverage(scope())
check("coverage counts the promised product files, not the shortlist",
      cover["product_files"] == 2 and cover["unread"] == ["src/rare.py"], cover)
check("the one product view excludes tests",
      sr.documented_paths(scope()) == {"src/app.py", "src/rare.py"})

# Adding a component widens the promise, so coverage cannot already be complete.
wider = scope(files=scope()["files"] + [
    {"path": "src/new.py", "disposition": "product", "reading": "unread"}])
check("adding a component changes the scope hash",
      sr.scope_hash(scope()) != sr.scope_hash(wider))
check("reading a file is progress, not a scope change",
      sr.scope_hash(scope()) == sr.scope_hash(scope(files=[
          dict(row, reading="analyzed") for row in scope()["files"]])))

if failures:
    for line in failures:
        print("   " + line)
    sys.exit(1)
print("\nall review/scope schema checks passed")
