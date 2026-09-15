# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/document/manual.py
# Regenerate: python3 tools/materialize.py
"""Question-driven manual model. Stdlib only; no network or package installation.

Run with --init PATH --index PATH to write an explicit unknown-answer draft.

The builder checks three things and not a fourth. It checks that every template
question was answered, that each citation points at a line range that exists, and --
for a `confirmed` answer -- that the answer names something the rest of the pipeline
already proved. It does not check that the cited lines say what the answer says; that
is what the prose review queue is for.

**A resolving citation is not a supporting one.** `src/api.py:34-51` can exist, be in
range, and have nothing to do with the sentence beside it, so location alone is a
weaker standard than every other claim in the same document is held to. `confirmed` is
the status that asserts the repository settles the question, so it is the one that has
to borrow its standing from a check that could have failed: a `verified` claim out of
verify_doc.py, or a `declared`/`observed` statement out of module-analysis.jsonl.
`inferred` carries the model's reading and says so, so evidence locations are the right
bar for it -- requiring a verified claim there would only push honest readings down to
`unknown`.
"""
import argparse
import json
from pathlib import Path


QUESTIONS = json.loads(Path(__file__).with_name("manual_questions.json").read_text())
DIAGRAMS = {"architecture/class_diagram": "diagram-manifest.json",
            "architecture/data_flow": "flow-diagram-manifest.json"}

# What a `confirmed` answer may borrow its standing from. These are the statuses the
# rest of the skill already lets into prose: hard rule 5 admits `verified` claims, and
# the two statement statuses that are not the model's own reading.
CONFIRMING_CLAIM_STATUS = ("verified",)
CONFIRMING_STATEMENT_STATUS = ("declared", "observed")


# Which template question each of the three analyses actually answers. Deliberately
# short: a mapping is justified only where the analysis holds the answer, not where it
# holds something adjacent. `usage/configuration` asks for a configuration schema and the
# operations analysis has procedures for configuring, which is a different question, so
# it is not here -- a prefilled answer that is true and says nothing is the failure the
# `A014` rule exists to catch, and it would arrive pre-approved.
#
# Each row is (question id, source key, section, what to call it in the sentence).
PREFILL = (
    ("1.2.1", "operations", "requirements", None),
    ("1.2.3", "operations", ("install", "build"), "installing and building"),
    ("2.1.1", "architecture", "components", None),
    ("2.1.3", "architecture", "relationships", None),
    ("2.2.1", "flows", "flows", None),
    ("3.1.1", "operations", ("run",), "running"),
    ("4.2.3", "operations", ("test",), "testing"),
    ("4.5.4", "operations", ("deploy", "release"), "deploying and releasing"),
)


def cite(rows):
    """Evidence entries from an analysis, in the shape build() checks.

    The three analyses record `line_start` and often no `line_end`; a citation with one
    line is the honest reading of that, not a range guessed outwards from it.

    A procedure and a flow hold their evidence on their steps rather than on themselves,
    so walking only the row would silently produce an unciteable answer -- and `prefill`
    drops an answer with no evidence, so the symptom is a procedure that quietly fails
    to prefill rather than one that prefills wrongly.
    """
    out = []
    seen = set()
    for row in rows:
        items = list(row.get("evidence", ()) or ())
        for step in row.get("steps", ()) or ():
            items.extend(step.get("evidence", ()) or ())
        for item in items:
            start = item.get("line_start")
            if not isinstance(item.get("path"), str) or not isinstance(start, int):
                continue
            entry = (item["path"], start, item.get("line_end") or start)
            if entry in seen:
                continue
            seen.add(entry)
            out.append({"path": entry[0], "line_start": entry[1], "line_end": entry[2]})
    return out


def procedures_of(operations, kinds):
    return [p for p in (operations or {}).get("procedures", ()) or ()
            if p.get("kind") in kinds]


def answer_from(source, section, label, data):
    """One prefilled answer, or None where the analysis recorded nothing.

    The text quotes the analysis rather than paraphrasing it, so a command reaches the
    page exactly as `validate_operations.py` matched it. Paraphrasing here would undo the
    one check in that schema a parser can settle.
    """
    if source == "operations" and section == "requirements":
        rows = [r for r in (data or {}).get("requirements", ()) or () if r.get("name")]
        if not rows:
            return None
        named = ", ".join("%s %s" % (r["name"], r.get("value", "").strip() or "(unversioned)")
                          for r in rows)
        return ("The repository declares these prerequisites: %s." % named, rows)
    if source == "operations":
        rows = procedures_of(data, section)
        if not rows:
            return None
        parts = []
        for procedure in rows:
            commands = [s["command"] for s in procedure.get("steps", ()) or ()
                        if s.get("command")]
            sentence = procedure.get("name") or procedure.get("id")
            if commands:
                sentence += ": " + ", ".join("`%s`" % c for c in commands)
            parts.append(sentence)
        return ("The repository records these procedures for %s. %s."
                % (label, "; ".join(parts)), rows)
    if source == "architecture" and section == "components":
        rows = [c for c in (data or {}).get("components", ()) or () if c.get("name")]
        if not rows:
            return None
        named = "; ".join("%s (%s)" % (c["name"], ", ".join(c.get("modules", ()) or ())
                                       or "no module recorded") for c in rows)
        return ("The architecture analysis groups the scanned modules into these "
                "components: %s." % named, rows)
    if source == "architecture" and section == "relationships":
        rows = [r for r in (data or {}).get("relationships", ()) or ()
                if r.get("from") and r.get("to")]
        if not rows:
            return None
        by_id = {c.get("id"): c.get("name", c.get("id"))
                 for c in (data or {}).get("components", ()) or ()}
        named = "; ".join("%s %s %s" % (by_id.get(r["from"], r["from"]),
                                        (r.get("kind") or "relates to").replace("_", " "),
                                        by_id.get(r["to"], r["to"])) for r in rows)
        # A relationship's id is the pair, not a row id, so the answer stands on the
        # components it joins -- those are what validate_architecture checked.
        endpoints = [c for c in (data or {}).get("components", ()) or ()
                     if c.get("id") in {r["from"] for r in rows} | {r["to"] for r in rows}]
        return ("The components cross these boundaries: %s." % named, rows + endpoints)
    if source == "flows":
        rows = [f for f in (data or {}).get("flows", ()) or () if f.get("steps")]
        if not rows:
            return None
        parts = []
        for flow in rows:
            hops = " -> ".join([flow["steps"][0].get("from", "?")]
                               + [s.get("to", "?") for s in flow["steps"]])
            parts.append("%s: %s" % (flow.get("name") or flow.get("id"), hops))
        return ("Each step below is a call verified at its call site. %s."
                % "; ".join(parts), rows)
    return None


def prefill(answers, extra):
    """Answer what the three analyses already settled, and leave the rest unknown.

    The point is not to save typing. These answers carry the checks their analyses
    passed -- a command matched character for character, a step read at its call site --
    and an answer written freehand over the same material carries none of that. Every
    other question stays `unknown` with its own text as the next check, because a
    prefilled guess arrives looking like a decided one.
    """
    filled = []
    # The same gate `build` applies, so prefill cannot write a `confirmed` answer that
    # the builder would then refuse. A row that does not qualify is left for the model
    # to answer itself rather than silently downgraded to `inferred`.
    qualifies = confirmable((), None, extra)
    for qid, source, section, label in PREFILL:
        data = (extra or {}).get(source)
        if not data or qid not in answers:
            continue
        produced = answer_from(source, section, label, data)
        if not produced:
            continue
        text, rows = produced
        evidence = cite(rows)
        ids = [r["id"] for r in rows if r.get("id") in qualifies]
        if not evidence or not ids:
            # Without both it could only be written as `inferred`, and a reading the
            # model did not make is not one it should be handed pre-written.
            continue
        answers[qid] = {"status": "confirmed", "text": text, "evidence": evidence,
                        "verified_ids": sorted(set(ids))}
        filled.append(qid)
    return filled


def scaffold(index, extra=None):
    # The marker belongs to the renderer, which prepends it to every `unknown` answer.
    # Carrying it here too rendered all 199 as "Unknown — evidence required. Unknown —
    # evidence required Check next: ...".
    answers = {q["id"]: {"status": "unknown", "text": "Not read yet.",
                         "next_check": q["text"], "evidence": []}
               for page in QUESTIONS for q in page["questions"]}
    prefilled = prefill(answers, extra)
    # `answers` are notes; `pages` is the document. Seeded empty rather than with a
    # section per question, because a section per question is the questionnaire this
    # step exists to stop producing -- the composing is the work, and a placeholder
    # would arrive looking like it was already done.
    return {"manual_version": 1, "index_hash": index.get("index_hash"),
            "prefilled": prefilled, "answers": answers,
            "pages": {page["id"]: {"sections": []} for page in QUESTIONS}}


def confirmable(claims, analysis, extra=None):
    """Every id a `confirmed` answer may stand on, mapped to what vouched for it.

    One list on the answer rather than one per source. The question an answer has to
    settle is "did anything that could have failed pass for this", and the five files
    that can say yes -- the claims, the module analysis, and the three C5-C7 analyses --
    answer it the same way. Keeping the origin is what lets the traceability page say
    which check stands behind a sentence; keeping five parallel fields would only make
    the answer schema harder to fill without making any of them stronger.

    An id absent from all of them is not a weaker citation, it is an unchecked one.
    """
    origins = {}
    for claim in claims or ():
        if claim.get("status") in CONFIRMING_CLAIM_STATUS and claim.get("id"):
            origins[claim["id"]] = "claim"
    for statement_id, statement in getattr(analysis, "by_id", {}).items():
        if statement.get("status") in CONFIRMING_STATEMENT_STATUS and statement_id:
            origins[statement_id] = "statement"
    extra = extra or {}
    # Each of these was validated by the script that owns its file -- but validation is
    # not confirmation, and taking every row that validated was the bug this guard fixes.
    # `validate_operations.py` accepts an `inferred` procedure, and exempts a step whose
    # status is `unknown` from carrying a command at all; such a row passed its schema
    # and had nothing mechanically checked about what it says. Letting it confirm an
    # answer would collapse the confirmed/inferred boundary from the other end.
    #
    # So a row qualifies on two counts: a status that is not the model's own reading, and
    # the piece of itself that a validator actually matched against the source.
    for key, section, label, checked in (
            ("operations", "procedures", "procedure", has_quoted_command),
            ("operations", "requirements", "requirement", has_quoted_value),
            ("flows", "flows", "flow", has_verified_step),
            ("architecture", "components", "component", holds_a_module)):
        for row in (extra.get(key) or {}).get(section, ()) or ():
            if not isinstance(row, dict) or not row.get("id"):
                continue
            if row.get("status") not in CONFIRMING_STATEMENT_STATUS:
                continue
            if not checked(row):
                continue
            origins[row["id"]] = label
    return origins


def has_quoted_command(procedure):
    """A step carrying a command, which `O006` matched character for character."""
    return any(step.get("command") for step in procedure.get("steps", ()) or ()
               if isinstance(step, dict))


def has_quoted_value(requirement):
    """`O006` matches a requirement's `value` the same way it matches a command."""
    return bool(str(requirement.get("value", "")).strip())


def has_verified_step(flow):
    """`F006` proved every step is a `calls` claim verified between its own two ends."""
    return bool(flow.get("steps"))


def holds_a_module(component):
    """`B003` and `B004` checked these names against the index, and for overlap.

    The weakest of the four, and named so: a component is a grouping decision, and the
    only mechanical thing about it is that the modules exist and belong to it alone.
    """
    return bool(component.get("modules"))


COMPOSABLE = ("confirmed", "inferred")


def read_answer(qid, answer, root, origins):
    """One answer checked and normalised. Nothing here is prose a reader will see.

    An answer is a *note*: what the repository says about one template question, with
    what it rests on. The page is composed from these afterwards, so the checks here are
    about whether the note is sound, never about how it reads.
    """
    if not isinstance(answer, dict):
        raise ValueError("%s: answer must be an object" % qid)
    status, text = answer.get("status"), answer.get("text")
    if status not in ("confirmed", "inferred", "unknown", "not_applicable"):
        raise ValueError("%s: invalid answer status" % qid)
    if not isinstance(text, str) or not text.strip() or text.strip() == "Answer:":
        raise ValueError("%s: answer text is required" % qid)
    evidence = answer.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("%s: evidence must be a list" % qid)
    if status in COMPOSABLE and not evidence:
        raise ValueError("%s: substantive answers require repository evidence" % qid)
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("%s: evidence must be an object" % qid)
        path, start, end = item.get("path"), item.get("line_start"), item.get("line_end")
        if not isinstance(path, str) or Path(path).is_absolute():
            raise ValueError("%s: evidence must use a repository-relative path" % qid)
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file():
            raise ValueError("%s: evidence is missing or outside the repository" % qid)
        if type(start) is not int or type(end) is not int or not 1 <= start <= end:
            raise ValueError("%s: invalid evidence line range" % qid)
        if end > len(target.read_text(encoding="utf-8").splitlines()):
            raise ValueError("%s: evidence line range exceeds file" % qid)
    verified_ids = answer.get("verified_ids", [])
    if not isinstance(verified_ids, list) \
            or any(not isinstance(r, str) for r in verified_ids):
        raise ValueError("%s: verified_ids must be a list of ids" % qid)
    unknown_refs = [r for r in verified_ids if r not in origins]
    if unknown_refs:
        # Naming an id nothing verified is the failure this rule exists for: it reads as
        # provenance and carries none.
        raise ValueError("%s: cites %s, which nothing in this run verified"
                         % (qid, ", ".join(sorted(unknown_refs)[:3])))
    if status == "confirmed" and not verified_ids:
        raise ValueError(
            "%s: `confirmed` must name a verified_id -- a verified claim, a recorded "
            "statement, or a validated procedure, flow or component. An answer the "
            "pipeline never checked is `inferred`" % qid)
    if status == "unknown" and not str(answer.get("next_check", "")).strip():
        raise ValueError("%s: unknown requires a concrete next_check" % qid)
    if status == "not_applicable" and not str(answer.get("reviewer", "")).strip():
        raise ValueError("%s: not_applicable requires reviewer confirmation" % qid)
    return {"id": qid, "status": status, "text": text, "evidence": evidence,
            "verified_ids": verified_ids, "next_check": answer.get("next_check", ""),
            "reviewer": answer.get("reviewer", "")}


def citation(item):
    return "%s:%d-%d" % (item["path"], item["line_start"], item["line_end"])


def read_section(page_id, order, section, notes, origins):
    """One composed section, checked against the answers it was written from.

    Composition is where a manual stops being a questionnaire, and it is also where an
    interpretation could quietly become a fact: prose that cites evidence no answer
    earned would carry provenance nothing checked. So a section may only name answers on
    its own page, may only cite what those answers cite, and takes the weaker of their
    statuses -- one `inferred` answer makes the section inferred, however many confirmed
    ones sit beside it.
    """
    where = "%s section %d" % (page_id, order)
    if not isinstance(section, dict):
        raise ValueError("%s: must be an object" % where)
    heading, body = section.get("heading"), section.get("body")
    for field, value in (("heading", heading), ("body", body)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("%s: %s is required" % (where, field))
    if heading.strip().endswith("?"):
        # The template question is the prompt, not the heading. A manual whose headings
        # are questions is the questionnaire this composition step exists to replace.
        raise ValueError("%s: heading %r is a question; write what the section is about"
                         % (where, heading.strip()[:60]))
    named = section.get("answers")
    if not isinstance(named, list) or not named:
        raise ValueError("%s: must name the answers it was written from" % where)
    cited_notes = []
    for qid in named:
        if qid not in notes:
            raise ValueError("%s: names %r, which is not a question on this page"
                             % (where, qid))
        note = notes[qid]
        if note["status"] not in COMPOSABLE:
            raise ValueError(
                "%s: names %s, which is %s -- an unanswered or excluded question is "
                "reported, never composed into prose" % (where, qid, note["status"]))
        cited_notes.append(note)
    allowed_evidence = {citation(e) for n in cited_notes for e in n["evidence"]}
    allowed_ids = {r for n in cited_notes for r in n["verified_ids"]}
    evidence = section.get("evidence") or [e for n in cited_notes for e in n["evidence"]]
    if not isinstance(evidence, list):
        raise ValueError("%s: evidence must be a list" % where)
    for item in evidence:
        if not isinstance(item, dict) or citation(item) not in allowed_evidence:
            raise ValueError(
                "%s: cites %r, which none of its answers cite -- composition may narrow "
                "what an answer rests on, never add to it"
                % (where, isinstance(item, dict) and citation(item) or item))
    verified_ids = section.get("verified_ids")
    if verified_ids is None:
        verified_ids = sorted(allowed_ids)
    if not isinstance(verified_ids, list) or set(verified_ids) - allowed_ids:
        raise ValueError("%s: verified_ids must be a subset of what its answers name"
                         % where)
    status = "inferred" if any(n["status"] == "inferred" for n in cited_notes) \
        else "confirmed"
    if status == "confirmed" and not verified_ids:
        raise ValueError("%s: confirmed sections keep the verified_id their answers "
                         "stand on" % where)
    text = body.strip()
    if status == "inferred":
        text = "Inferred: " + text
    citations = sorted({citation(e) for e in evidence})
    if citations:
        text += "\n\nEvidence: " + "; ".join(citations)
    slug = "%s:%d" % (page_id, order)
    return [
        {"id": "heading:" + slug, "type": "subheading", "text": heading.strip()},
        {"id": "section:" + slug, "type": "prose", "text": text,
         "manual_block": True, "manual_answers": sorted(n["id"] for n in cited_notes),
         "answer_status": status, "evidence": evidence,
         "claim_refs": [r for r in verified_ids if origins.get(r) == "claim"],
         "analysis_refs": [r for r in verified_ids if origins.get(r) == "statement"],
         "verified_by": [{"id": r, "source": origins[r]} for r in sorted(verified_ids)]}]


def gaps_block(page_id, notes, composed):
    """What the page could not say, in one place rather than scattered through it.

    A reader is owed the absences, and the run is held back by them -- but an unanswered
    question is a note about the document, not a section of it. Collecting them under one
    marked block keeps the prose readable without letting a gap go unreported.
    """
    unknown = [n for n in notes.values() if n["status"] == "unknown"]
    excluded = [n for n in notes.values() if n["status"] == "not_applicable"]
    uncomposed = [n for n in notes.values()
                  if n["status"] in COMPOSABLE and n["id"] not in composed]
    if not (unknown or excluded or uncomposed):
        return None
    parts = []
    if unknown:
        parts.append("Not documented: %d question(s) the repository does not answer "
                     "yet (%s)." % (len(unknown), ", ".join(sorted(n["id"] for n in unknown))))
    if excluded:
        parts.append("Not applicable here: %s."
                     % ", ".join(sorted(n["id"] for n in excluded)))
    if uncomposed:
        parts.append("Answered but not yet written into this page: %s."
                     % ", ".join(sorted(n["id"] for n in uncomposed)))
    return {"id": "gaps:" + page_id, "type": "prose", "text": " ".join(parts),
            "absence": True}


def build(index, content, diagrams, root, claims=(), analysis=None, extra=None):
    if not isinstance(content, dict) or content.get("manual_version") != 1:
        raise ValueError("manual requires --manual-analysis with manual_version 1")
    if not index.get("index_hash") or content.get("index_hash") != index["index_hash"]:
        raise ValueError("manual analysis is missing its scan identity or is stale")
    answers = content.get("answers")
    expected = {q["id"] for p in QUESTIONS for q in p["questions"]}
    if not isinstance(answers, dict) or set(answers) != expected:
        raise ValueError("manual answers must contain exactly every template question ID")
    composed_pages = content.get("pages") or {}
    if not isinstance(composed_pages, dict):
        raise ValueError("manual `pages` must be a map of page id to its sections")
    unknown_pages = set(composed_pages) - {p["id"] for p in QUESTIONS}
    if unknown_pages:
        raise ValueError("manual `pages` names %s, which the template does not have"
                         % ", ".join(sorted(unknown_pages)[:3]))
    origins = confirmable(claims, analysis, extra)
    cited, unresolved, uncomposed, missing_diagrams = set(), [], [], []
    pages, root = [], Path(root).resolve()
    for order, spec in enumerate(QUESTIONS, 1):
        notes = {q["id"]: read_answer(q["id"], answers[q["id"]], root, origins)
                 for q in spec["questions"]}
        unresolved.extend(n["id"] for n in notes.values() if n["status"] == "unknown")
        blocks, composed = [], set()
        sections = (composed_pages.get(spec["id"]) or {}).get("sections") or []
        if not isinstance(sections, list):
            raise ValueError("%s: sections must be a list" % spec["id"])
        for number, section in enumerate(sections, 1):
            produced = read_section(spec["id"], number, section, notes, origins)
            blocks.extend(produced)
            composed.update(produced[1]["manual_answers"])
            cited.update(r["id"] for r in produced[1]["verified_by"])
        uncomposed.extend(n["id"] for n in notes.values()
                          if n["status"] in COMPOSABLE and n["id"] not in composed)
        gaps = gaps_block(spec["id"], notes, composed)
        if gaps:
            blocks.append(gaps)
        if not blocks:
            blocks.append({"id": "empty:" + spec["id"], "type": "prose", "absence": True,
                           "text": "Nothing is recorded for this page yet."})
        if spec["id"] in DIAGRAMS:
            directory = Path(diagrams) if diagrams else None
            manifest = directory / DIAGRAMS[spec["id"]] if directory else None
            found = []
            if manifest and manifest.is_file():
                data = json.loads(manifest.read_text())
                if spec["id"] == "architecture/data_flow":
                    if data.get("index_hash") != index["index_hash"] or data.get("validated") is not True:
                        raise ValueError("manual flow diagram manifest is stale or unvalidated")
                elif data.get("schema_version") != 3:
                    raise ValueError("unsupported manual class diagram manifest")
                for view in data.get("views", []):
                    name = view.get("file", "")
                    target = (directory / name).resolve()
                    if (name.endswith(".puml") and directory.resolve() in target.parents
                            and target.is_file()):
                        found.append({"id": "diagram:" + spec["id"] + ":" + name,
                                      "type": "plantuml", "src": "_diagrams/" + name,
                                      "alt": spec["title"]})
            blocks.extend(found)
            if not found:
                missing_diagrams.append(spec["id"])
                blocks.append({"id": "missing:" + spec["id"], "type": "prose",
                               "absence": True,
                               "text": "Unknown — evidence required. Required diagram is missing."})
        pages.append({"id": spec["id"], "title": spec["title"], "mandatory": True,
                      "order": order, "blocks": blocks, "covers": [], "analysis_ids": []})
    # The review belongs at the end of the appendix, not ahead of Getting Started.
    pages = pages[1:] + pages[:1]
    for order, page in enumerate(pages, 1):
        page["order"] = order
    # Carry the cited rows, not every row: a reference has to resolve inside the
    # document it is written in, and shipping the whole claim set would put material on
    # the page that no answer stands on.
    by_claim = {c.get("id"): c for c in claims or ()}
    by_statement = getattr(analysis, "by_id", {})
    by_source = {}
    for ref in cited:
        by_source.setdefault(origins[ref], []).append(ref)
    sections_written = sum(1 for p in pages for b in p["blocks"] if b.get("manual_block"))
    return {"preset": "manual", "pages": pages, "authored_pages": [],
            "claims": [by_claim[i] for i in sorted(cited) if i in by_claim],
            "statements": [by_statement[i] for i in sorted(cited) if i in by_statement],
            "coverage": index.get("coverage", {}),
            "source_revision": (index.get("source") or {}).get("revision"),
            "source_dirty": (index.get("source") or {}).get("dirty"),
            "manual_coverage": {"total": len(expected), "unresolved": unresolved,
                                "uncomposed": uncomposed, "sections": sections_written,
                                "missing_diagrams": missing_diagrams,
                                "verified_ids_cited": {k: sorted(v)
                                                       for k, v in sorted(by_source.items())}}}


def validate_document(doc):
    problems = []
    pages = doc.get("pages", [])
    block_ids = [b.get("id") for p in pages for b in p.get("blocks", [])]
    if len(block_ids) != len(set(block_ids)):
        problems.append("manual contains duplicate block IDs")
    for page in pages:
        for block in page.get("blocks", []):
            if not block.get("manual_block"):
                continue
            if not str(block.get("text", "")).strip():
                problems.append("manual contains an empty section")
            if block.get("answer_status") not in COMPOSABLE:
                problems.append("manual contains a section with an invalid status")
            if not block.get("evidence"):
                problems.append("manual contains a section without evidence")
            if not block.get("manual_answers"):
                problems.append("manual contains a section naming no answer")
    if [p.get("id") for p in pages] != [p["id"] for p in QUESTIONS[1:] + QUESTIONS[:1]]:
        problems.append("manual pages must follow the complete template order")
    # Every page still has to say something, but what it says is now composed rather
    # than one block per question -- so the check is that nothing is blank, not that the
    # template's questions appear in order on the page.
    for page in pages:
        if not page.get("blocks"):
            problems.append("%s has no content at all" % page.get("id"))
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--architecture", help="architecture-analysis.json")
    parser.add_argument("--flows", help="flow-analysis.json")
    parser.add_argument("--operations", help="operations-analysis.json")
    args = parser.parse_args()
    index = json.loads(Path(args.index).read_text())
    extra = {}
    for key, path in (("architecture", args.architecture), ("flows", args.flows),
                      ("operations", args.operations)):
        if not path:
            continue
        loaded = json.loads(Path(path).read_text())
        stated = loaded.get("index_hash")
        if stated != index.get("index_hash"):
            # A file from an earlier run names real modules and prefills cleanly. The
            # identity is the only thing that tells it from today's.
            raise SystemExit("FAIL %s was written against %s, the index is %s"
                             % (path, stated, index.get("index_hash")))
        extra[key] = loaded
    draft = scaffold(index, extra)
    # Exclusive creation protects an analysis the agent already wrote.
    with open(args.init, "x", encoding="utf-8") as handle:
        json.dump(draft, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("wrote %s: %d question(s), %d prefilled from the analyses"
          % (args.init, len(draft["answers"]), len(draft["prefilled"])))
