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


def confirmable(claims, analysis):
    """The claim and statement ids a `confirmed` answer is allowed to stand on.

    Built from the same two files the rest of the run is checked against, so an id that
    passes here passed verify_doc.py or validate_analysis.py first. An id absent from
    both is not a weaker citation, it is an unchecked one.
    """
    claim_ids = {c.get("id") for c in claims or ()
                 if c.get("status") in CONFIRMING_CLAIM_STATUS}
    statement_ids = set()
    for statement_id, statement in getattr(analysis, "by_id", {}).items():
        if statement.get("status") in CONFIRMING_STATEMENT_STATUS:
            statement_ids.add(statement_id)
    return claim_ids - {None}, statement_ids - {None}


def build(index, content, diagrams, root, claims=(), analysis=None):
    if not isinstance(content, dict) or content.get("manual_version") != 1:
        raise ValueError("manual requires --manual-analysis with manual_version 1")
    if not index.get("index_hash") or content.get("index_hash") != index["index_hash"]:
        raise ValueError("manual analysis is missing its scan identity or is stale")
    answers = content.get("answers")
    expected = {q["id"] for p in QUESTIONS for q in p["questions"]}
    if not isinstance(answers, dict) or set(answers) != expected:
        raise ValueError("manual answers must contain exactly every template question ID")
    known_claims, known_statements = confirmable(claims, analysis)
    cited_claims, cited_statements = set(), set()
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
            claim_refs = answer.get("claim_ids", [])
            analysis_refs = answer.get("statement_ids", [])
            for label, refs in (("claim_ids", claim_refs),
                                ("statement_ids", analysis_refs)):
                if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
                    raise ValueError("%s: %s must be a list of ids" % (qid, label))
            unknown_refs = ([r for r in claim_refs if r not in known_claims]
                            + [r for r in analysis_refs if r not in known_statements])
            if unknown_refs:
                # Naming an id nothing verified is the failure this rule exists for: it
                # reads as provenance and carries none.
                raise ValueError(
                    "%s: cites %s, which no verified claim or recorded statement holds"
                    % (qid, ", ".join(sorted(unknown_refs)[:3])))
            if status == "confirmed" and not (claim_refs or analysis_refs):
                raise ValueError(
                    "%s: `confirmed` must name a verified claim_id or a statement_id; "
                    "an answer the pipeline never checked is `inferred`" % qid)
            cited_claims.update(claim_refs)
            cited_statements.update(analysis_refs)
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
                 "analysis_refs": analysis_refs}])
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
    return {"preset": "manual", "pages": pages, "authored_pages": [],
            "claims": [by_claim[i] for i in sorted(cited_claims) if i in by_claim],
            "statements": [by_statement[i] for i in sorted(cited_statements)
                           if i in by_statement],
            "coverage": index.get("coverage", {}),
            "source_revision": (index.get("source") or {}).get("revision"),
            "source_dirty": (index.get("source") or {}).get("dirty"),
            "manual_coverage": {"total": len(expected), "unresolved": unresolved,
                                "missing_diagrams": missing_diagrams,
                                "confirmed_with_proof": len(cited_claims) + len(cited_statements)}}


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
