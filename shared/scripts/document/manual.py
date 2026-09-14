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


def scaffold(index):
    return {"manual_version": 1, "index_hash": index.get("index_hash"),
            "answers": {q["id"]: {"status": "unknown", "text": "Unknown — evidence required",
                                     "next_check": q["text"], "evidence": []}
                        for page in QUESTIONS for q in page["questions"]}}


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
    # Each of these was validated by the script that owns its file -- a procedure's
    # command was matched character for character (O006), a flow's every step is a call
    # verified at its call site (F006), a component's shape and evidence passed B002-B012.
    # That is the same bar the two above clear, reached by a different validator.
    for key, section, label in (("operations", "procedures", "procedure"),
                                ("flows", "flows", "flow"),
                                ("architecture", "components", "component")):
        for row in (extra.get(key) or {}).get(section, ()) or ():
            if isinstance(row, dict) and row.get("id"):
                origins[row["id"]] = label
    return origins


def build(index, content, diagrams, root, claims=(), analysis=None, extra=None):
    if not isinstance(content, dict) or content.get("manual_version") != 1:
        raise ValueError("manual requires --manual-analysis with manual_version 1")
    if not index.get("index_hash") or content.get("index_hash") != index["index_hash"]:
        raise ValueError("manual analysis is missing its scan identity or is stale")
    answers = content.get("answers")
    expected = {q["id"] for p in QUESTIONS for q in p["questions"]}
    if not isinstance(answers, dict) or set(answers) != expected:
        raise ValueError("manual answers must contain exactly every template question ID")
    origins = confirmable(claims, analysis, extra)
    cited = set()
    pages, unresolved, missing_diagrams = [], [], []
    root = Path(root).resolve()
    for order, spec in enumerate(QUESTIONS, 1):
        blocks = []
        for question in spec["questions"]:
            qid = question["id"]
            answer = answers[qid]
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
            if status in ("confirmed", "inferred") and not evidence:
                raise ValueError("%s: substantive answers require repository evidence" % qid)
            citations = []
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
                citations.append("%s:%d-%d" % (path, start, end))
            verified_ids = answer.get("verified_ids", [])
            if not isinstance(verified_ids, list) \
                    or any(not isinstance(r, str) for r in verified_ids):
                raise ValueError("%s: verified_ids must be a list of ids" % qid)
            unknown_refs = [r for r in verified_ids if r not in origins]
            if unknown_refs:
                # Naming an id nothing verified is the failure this rule exists for: it
                # reads as provenance and carries none.
                raise ValueError(
                    "%s: cites %s, which nothing in this run verified"
                    % (qid, ", ".join(sorted(unknown_refs)[:3])))
            if status == "confirmed" and not verified_ids:
                raise ValueError(
                    "%s: `confirmed` must name a verified_id -- a verified claim, a "
                    "recorded statement, or a validated procedure, flow or component. "
                    "An answer the pipeline never checked is `inferred`" % qid)
            cited.update(verified_ids)
            claim_refs = [r for r in verified_ids if origins[r] == "claim"]
            analysis_refs = [r for r in verified_ids if origins[r] == "statement"]
            if status == "unknown":
                if not str(answer.get("next_check", "")).strip():
                    raise ValueError("%s: unknown requires a concrete next_check" % qid)
                unresolved.append(qid)
                text = "Unknown — evidence required. %s Check next: %s" % (
                    text, answer["next_check"])
            elif status == "not_applicable":
                if not str(answer.get("reviewer", "")).strip():
                    raise ValueError("%s: not_applicable requires reviewer confirmation" % qid)
                text = "Not applicable: %s (reviewed by %s)" % (text, answer["reviewer"])
            elif status == "inferred":
                text = "Inferred: " + text
            if citations:
                text += "\n\nEvidence: " + "; ".join(citations)
            blocks.extend([
                {"id": "question:" + qid, "type": "subheading", "text": question["text"]},
                {"id": "answer:" + qid, "type": "prose", "text": text,
                 "manual_question": qid, "answer_status": status,
                 "evidence": evidence, "claim_refs": claim_refs,
                 "analysis_refs": analysis_refs,
                 "verified_by": [{"id": r, "source": origins[r]}
                                 for r in sorted(verified_ids)]}])
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
    return {"preset": "manual", "pages": pages, "authored_pages": [],
            "claims": [by_claim[i] for i in sorted(cited) if i in by_claim],
            "statements": [by_statement[i] for i in sorted(cited) if i in by_statement],
            "coverage": index.get("coverage", {}),
            "source_revision": (index.get("source") or {}).get("revision"),
            "source_dirty": (index.get("source") or {}).get("dirty"),
            "manual_coverage": {"total": len(expected), "unresolved": unresolved,
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
            if not block.get("manual_question"):
                continue
            if not str(block.get("text", "")).strip():
                problems.append("manual contains an empty answer")
            status = block.get("answer_status")
            if status not in ("confirmed", "inferred", "unknown", "not_applicable"):
                problems.append("manual contains an invalid answer status")
            if status in ("confirmed", "inferred") and not block.get("evidence"):
                problems.append("manual contains an answer without evidence")
    if [p.get("id") for p in pages] != [p["id"] for p in QUESTIONS[1:] + QUESTIONS[:1]]:
        problems.append("manual pages must follow the complete template order")
    for spec in QUESTIONS:
        page = next((p for p in pages if p.get("id") == spec["id"]), {})
        actual = [b.get("manual_question") for b in page.get("blocks", [])
                  if b.get("type") == "prose" and b.get("manual_question")]
        if actual != [q["id"] for q in spec["questions"]]:
            problems.append("%s is missing template answers" % spec["id"])
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", required=True)
    parser.add_argument("--index", required=True)
    args = parser.parse_args()
    index = json.loads(Path(args.index).read_text())
    # Exclusive creation protects an analysis the agent already wrote.
    with open(args.init, "x", encoding="utf-8") as handle:
        json.dump(scaffold(index), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
