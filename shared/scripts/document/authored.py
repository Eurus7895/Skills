"""The ledger for the manual's authored pages. Stdlib only; no network.

Six pages in the template carry questions no repository answers: a glossary, an FAQ, a
changelog, a troubleshooting table, a compliance statement, a bibliography. `manual.py`
excludes them from `GENERATED` for a reason that still holds -- asking the run 38
questions it has no source for buys 38 more `unknown`s and drags `answer_mode` down for
gaps that were never the run's to fill.

**But "not the run's to fill" was implemented as silence.** The run named the pages, the
report said they were not generated, and nothing else happened: no scaffold, no evidence
handed over, no obligation recorded, and a published manual with six mandatory pages
absent still reported a preset requirement rather than a blocked publication.

This module is the other half of that decision. The pages stay out of `answer_mode`, and
gain a ledger of their own:

    authored_mode   how much of what only a person can write has been written

and, per page, the evidence this run already verified that bears on it.

**Nothing here extracts anything.** Every row it offers was collected, cited and checked
by a component that already runs -- `failure` statements by `analyze`, procedures by
`validate_operations.py`, assets by `scan_repo.py`. A second extractor beside them would
be a second, unvalidated path to the same material, which is the duplication this skill
spends its budget avoiding. So this is a router: it groups what exists by the page that
needs it, and says plainly what it found nothing for.
"""
import json
from pathlib import Path


AUTHORED_VERSION = 1

SCAFFOLDED, DRAFTED, COMPLETE, WAIVED = "scaffolded", "drafted", "complete", "waived"
STATUSES = (SCAFFOLDED, DRAFTED, COMPLETE, WAIVED)
# The two that release the publication gate. `drafted` deliberately does not: a draft is
# what gets reviewed, and treating it as done would publish the review's input as its
# output.
SETTLED = (COMPLETE, WAIVED)

# The same bar `manual.py` sets for a verified_id: a status that is not the model's own
# reading. An `inferred` statement is a reading offered as a starting point elsewhere;
# here it would arrive looking like evidence for a page whose whole problem is that
# evidence is thin.
OFFERED_STATUS = ("declared", "observed")


# Who each page is for and what it owes them. Written here rather than in the question
# template because it is guidance for the person filling the scaffold, not a question the
# run could answer.
PURPOSE = {
    "appendix/troubleshooting": (
        "Let a user resolve a failure without reading source.",
        "An operator running the system, who has an error in front of them."),
    "appendix/faq": (
        "Answer what users actually ask, briefly, with a pointer to the full page.",
        "A new user who has skimmed the quick start and hit a question."),
    "appendix/glossary": (
        "Define the domain and project terms the rest of the manual assumes.",
        "A reader outside the team, for whom the terms are not yet obvious."),
    "appendix/references": (
        "Record what this project depends on and what governs it.",
        "A maintainer or auditor tracing a requirement to its source."),
    "appendix/compliance": (
        "State the regulatory, licensing and security position, and who owns it.",
        "An auditor, or a maintainer answering to one."),
    "appendix/changelog": (
        "Say what changed between releases, and what a reader must do about it.",
        "A user upgrading from an earlier version."),
}

# What each page may draw on, named by the component that produced it. A page absent from
# a row here gets nothing from that source -- and the scaffold says so rather than
# offering a thin substitute.
STATEMENT_KINDS = {"appendix/troubleshooting": ("failure",)}
PROCEDURE_PAGES = ("appendix/troubleshooting", "appendix/faq")
ASSET_KINDS = {"appendix/changelog": ("changelog",),
               "appendix/references": ("licence", "packaging"),
               "appendix/faq": ("readme",)}

# `compliance` asserts a legal position rather than describing behaviour, and an unowned
# compliance claim is worse than an absent one: a reader cannot tell a considered "this
# does not apply" from nobody having looked. So it starts waived, visibly and by default,
# and becomes an assertion only when a person puts their name to it.
DEFAULT_WAIVED = ("appendix/compliance",)
DEFAULT_WAIVER = ("No owner has claimed this page. Nothing in the repository asserts a "
                  "compliance position, and this run does not assert one on its behalf.")


def _cite(evidence):
    """`path:start-end` for the first location a row carries, or None."""
    for item in evidence or ():
        if not isinstance(item, dict):
            continue
        path, start, end = item.get("path"), item.get("line_start"), item.get("line_end")
        if isinstance(path, str) and type(start) is int and type(end) is int:
            return "%s:%d-%d" % (path, start, end)
    return None


def offered(page_id, index=None, analysis=None, extra=None):
    """Evidence this run already verified that bears on `page_id`.

    Each row keeps the id it has elsewhere in the pipeline, so a person filling the
    scaffold cites what the rest of the document cites rather than a copy of it.
    """
    index, extra = index or {}, extra or {}
    rows = []
    for kind in STATEMENT_KINDS.get(page_id, ()):
        for statement in (analysis.of_kind(kind, OFFERED_STATUS) if analysis else ()):
            rows.append({"ref": statement.get("id"), "source": "statement",
                         "kind": kind, "cite": _cite(statement.get("evidence")),
                         "text": statement.get("text", "")})
    if page_id in PROCEDURE_PAGES:
        for procedure in (extra.get("operations") or {}).get("procedures", ()) or ():
            if not isinstance(procedure, dict) or not procedure.get("id"):
                continue
            if procedure.get("status") not in OFFERED_STATUS:
                continue
            rows.append({"ref": procedure["id"], "source": "procedure",
                         "kind": procedure.get("kind", ""),
                         "cite": _cite(procedure.get("evidence")),
                         "text": procedure.get("name", "")})
    wanted = ASSET_KINDS.get(page_id, ())
    for asset in index.get("assets", ()) or ():
        if not isinstance(asset, dict) or asset.get("kind") not in wanted:
            continue
        lines = asset.get("lines") or 0
        rows.append({"ref": asset.get("path"), "source": "asset",
                     "kind": asset.get("kind"),
                     "cite": "%s:1-%d" % (asset["path"], lines) if lines else None,
                     "text": ""})
    return [r for r in rows if r.get("ref")]


def absences(page_id, index=None, analysis=None, extra=None):
    """What the run looked for on this page's behalf and did not find.

    The field that keeps a scaffold honest. A troubleshooting page built from four
    `failure` statements looks the same as one built from forty until something says how
    many modules were silent -- and the difference decides whether the thin page is the
    repository's fault or the analysis's.
    """
    index, extra, out = index or {}, extra or {}, []
    for kind in STATEMENT_KINDS.get(page_id, ()):
        if analysis is None:
            out.append("no module analysis was available, so no %s statement could be "
                       "offered" % kind)
            continue
        described = {s.get("path") for s in analysis.of_kind(kind, OFFERED_STATUS)}
        silent = sorted(analysis.modules() - described)
        if silent:
            out.append("%d of %d analysed module(s) carry no %s statement (%s%s)"
                       % (len(silent), len(analysis.modules()), kind,
                          ", ".join(silent[:3]), ", ..." if len(silent) > 3 else ""))
    if page_id in PROCEDURE_PAGES and not (extra.get("operations") or {}).get("procedures"):
        out.append("no validated procedure was recorded, so no operational step could be "
                   "offered")
    for kind in ASSET_KINDS.get(page_id, ()):
        if not any(a.get("kind") == kind for a in index.get("assets", ()) or ()
                   if isinstance(a, dict)):
            out.append("the repository holds no %s file" % kind)
    if not (STATEMENT_KINDS.get(page_id) or ASSET_KINDS.get(page_id)
            or page_id in PROCEDURE_PAGES):
        out.append("nothing in a repository answers this page; it is written from "
                   "knowledge the source does not hold")
    return out


def scaffold_row(page, index=None, analysis=None, extra=None):
    """The ledger row for one authored page, as a run that has written nothing sees it."""
    page_id = page["id"]
    purpose, audience = PURPOSE.get(page_id, ("", ""))
    waived = page_id in DEFAULT_WAIVED
    return {"authored_version": AUTHORED_VERSION, "page_id": page_id,
            "title": page["title"], "purpose": purpose, "audience": audience,
            "status": WAIVED if waived else SCAFFOLDED,
            "owner": None,
            "waiver_reason": DEFAULT_WAIVER if waived else None,
            "default_waiver": waived,
            "questions": [{"id": q["id"], "text": q["text"], "answered": False}
                          for q in page.get("questions", ())],
            "evidence_offered": offered(page_id, index, analysis, extra),
            "evidence_absent": absences(page_id, index, analysis, extra)}


def read_row(row, known):
    """One ledger row checked. Returns it normalised; raises on anything unsound."""
    if not isinstance(row, dict):
        raise ValueError("authored ledger rows must be objects")
    page_id = row.get("page_id")
    if page_id not in known:
        raise ValueError("authored ledger names %r, which is not an authored page"
                         % (page_id,))
    if row.get("authored_version") != AUTHORED_VERSION:
        raise ValueError("%s: authored ledger rows are authored_version %d"
                         % (page_id, AUTHORED_VERSION))
    status = row.get("status")
    if status not in STATUSES:
        raise ValueError("%s: status must be one of %s" % (page_id, ", ".join(STATUSES)))
    owner = str(row.get("owner") or "").strip()
    reason = str(row.get("waiver_reason") or "").strip()
    # **Which pages may carry a default waiver is settled here, not by the row.** Trusting
    # the row's own boolean made the exemption forgeable: `default_waiver: true` with
    # `status: waived` on any page skipped both the owner and the reason check, so a
    # hand-edited FAQ or troubleshooting row could clear the publication gate while the
    # page stayed unwritten. Only `DEFAULT_WAIVED` decides, and a row claiming it
    # elsewhere is refused rather than quietly downgraded -- somebody wrote that, and it
    # asks for an exemption the page does not have.
    claims_default = bool(row.get("default_waiver"))
    if claims_default and page_id not in DEFAULT_WAIVED:
        raise ValueError(
            "%s: only %s may carry `default_waiver`. Every other page is waived by a "
            "person, with an owner and a reason"
            % (page_id, ", ".join(DEFAULT_WAIVED)))
    if status == WAIVED and not claims_default:
        # A waiver is an answer -- "we looked, and this page is not needed here" -- and an
        # answer has someone behind it. The default waiver is the one exception, and it
        # says in its own text that nobody has looked.
        if not owner:
            raise ValueError("%s: a waived page names the owner who waived it" % page_id)
        if not reason:
            raise ValueError("%s: a waived page records why, or it is `scaffolded` "
                             "wearing a verdict" % page_id)
    if claims_default and status not in (WAIVED, COMPLETE, DRAFTED):
        raise ValueError("%s: a default-waived page is waived, drafted or complete"
                         % page_id)
    return dict(row, owner=owner or None, waiver_reason=reason or None)


def ledger(pages, index=None, analysis=None, extra=None, recorded=()):
    """Every authored page's row: what a person recorded, or a fresh scaffold.

    The evidence fields are recomputed every time rather than carried over. They describe
    this run's index and this run's analysis, and a row that kept yesterday's offering
    would point a writer at statements that may no longer exist.
    """
    known = {page["id"]: page for page in pages}
    by_page = {}
    for row in recorded or ():
        checked = read_row(row, known)
        by_page[checked["page_id"]] = checked
    out = []
    for page in pages:
        fresh = scaffold_row(page, index, analysis, extra)
        held = by_page.get(page["id"])
        if held:
            fresh.update({k: held[k] for k in
                          ("status", "owner", "waiver_reason", "default_waiver")
                          if k in held})
            if isinstance(held.get("questions"), list):
                answered = {q.get("id") for q in held["questions"]
                            if isinstance(q, dict) and q.get("answered")}
                for question in fresh["questions"]:
                    question["answered"] = question["id"] in answered
        out.append(fresh)
    return out


def unsettled(rows):
    """Pages that still owe the reader something, as (page_id, status)."""
    return [(r["page_id"], r["status"]) for r in rows if r["status"] not in SETTLED]


def authored_mode(rows):
    """How much of what only a person can write has been written.

    Deliberately not folded into `answer_mode`. That measures how much of the template
    *the run* answered, and a page the run was never asked to answer must not count
    against it -- nor be quietly excused by it.
    """
    if not rows:
        return COMPLETE, 0, 0
    settled = sum(1 for r in rows if r["status"] in SETTLED)
    written = sum(1 for r in rows if r["status"] == COMPLETE)
    if settled == len(rows):
        return "settled" if written < len(rows) else "written", settled, len(rows)
    if settled:
        return "partial", settled, len(rows)
    return "unwritten", settled, len(rows)


def load(path, pages, index=None, analysis=None, extra=None):
    """Read a ledger file if one exists, else scaffold every page fresh."""
    recorded = []
    if path and Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                recorded.append(json.loads(line))
    return ledger(pages, index, analysis, extra, recorded)


# What the file on disk is *for*. The evidence fields are this run's view of this run's
# index, recomputed on every build; persisting them would put a stale reading list in a
# file a person edits, and the next run would silently disagree with what they read. So
# the record keeps only what a person owns, and the document carries the computed view.
DURABLE = ("authored_version", "page_id", "status", "owner", "waiver_reason",
           "default_waiver")


def dump(rows, path):
    """Write the ledger as JSONL, one page per line -- the human state, not the view."""
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            keep = {k: row[k] for k in DURABLE if k in row}
            keep["questions"] = [{"id": q["id"], "answered": bool(q.get("answered"))}
                                 for q in row.get("questions", ())]
            handle.write(json.dumps(keep, ensure_ascii=False, sort_keys=True) + "\n")
