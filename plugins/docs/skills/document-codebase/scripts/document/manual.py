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

import authored


MANUAL_VERSION = 2

QUESTIONS = json.loads(Path(__file__).with_name("manual_questions.json").read_text())

# Pages whose questions a repository cannot answer: a glossary, an FAQ, a changelog, a
# troubleshooting table, a compliance statement, a bibliography. `presets.md` already
# names most of them for `handbook` -- "things a person knows" -- and the same reasoning
# applies here, only it had not been applied.
#
# They are declared, never generated. The alternative is asking the run 38 questions it
# has no source for, which buys 38 more `unknown`s and drags `answer_mode` down for
# gaps that were never the run's to fill. A page the report names as authored is honest;
# a page of unknowns pretending the run tried is not.
#
# That reasoning still holds, and it used to end here -- which made "not the run's to
# fill" indistinguishable from "nobody's to fill". `authored.py` carries the other half:
# the pages stay out of `answer_mode`, and gain a ledger that records the obligation, the
# evidence this run already verified for them, and what it found nothing for.
GENERATED = [page for page in QUESTIONS if not page.get("authored")]
AUTHORED = [page for page in QUESTIONS if page.get("authored")]

# The documentation-wide review is first in the template and belongs last in the document.
# Named once here rather than implied by a `pages[1:] + pages[:1]` slice, because the
# authored pages need the same answer and a slice cannot give it to them.
REVIEW_PAGE = GENERATED[0]["id"]


def template_order():
    """Every page id to its place in the delivered document, generated and authored alike.

    **One order over the whole template, not one per kind.** Generated pages were rotated
    so the review came last, and authored pages were then given positions after every
    generated one -- which put compliance, glossary, troubleshooting, FAQ, references and
    changelog *after* the review, so the final review was no longer final. The template
    already interleaves them (`appendix/output_structure` sits between `references` and
    `changelog`), and that interleaving is the intended reading order.
    """
    ordered = [page["id"] for page in QUESTIONS if page["id"] != REVIEW_PAGE]
    ordered.append(REVIEW_PAGE)
    return {page_id: position for position, page_id in enumerate(ordered, 1)}
DIAGRAMS = {"architecture/class_diagram": "diagram-manifest.json",
            "architecture/data_flow": "flow-diagram-manifest.json"}

# What a `confirmed` answer may borrow its standing from. These are the statuses the
# rest of the skill already lets into prose: hard rule 5 admits `verified` claims, and
# the two statement statuses that are not the model's own reading.
CONFIRMING_CLAIM_STATUS = ("verified",)
CONFIRMING_STATEMENT_STATUS = ("declared", "observed")


def scaffold(index, extra=None, claims=(), analysis=None):
    """An empty draft: every slot unanswered, and the facts available to answer it with.

    **The initializer writes no prose.** It used to compose a sentence per mapped
    question and mark it answered, which put text in the manual that no one had written
    and no one had reviewed -- and it arrived looking decided, which is the worst of both.
    Turning an extracted row into a sentence is the model's work, because deciding what a
    setting *means* is the part the extraction cannot do.

    What it does hand over is `facts`: the ids this run verified, grouped by what vouched
    for them. That is a reading list, not an answer -- the model still has to look at each
    one, decide what it says, and write the sentence it stands behind.
    """
    answers = {q["id"]: {"basis": "unknown", "completeness": "unanswered",
                         "content_review": "pending",
                         "text": "TODO — not yet answered.",
                         "next_check": "Read the source for this before answering "
                                       "`unknown`.",
                         "evidence": [], "verified_ids": [], "facets_missing": []}
               for page in GENERATED for q in page["questions"]}
    facts = {}
    for ref, source in confirmable(claims, analysis, extra).items():
        facts.setdefault(source, []).append(ref)
    # `answers` are notes; `pages` is the document. Seeded empty rather than with a
    # section per question, because a section per question is the questionnaire this
    # step exists to stop producing -- the composing is the work, and a placeholder
    # would arrive looking like it was already done.
    return {"manual_version": MANUAL_VERSION, "index_hash": index.get("index_hash"),
            "facts": {k: sorted(v) for k, v in sorted(facts.items())},
            "answers": answers,
            "pages": {page["id"]: {"sections": []} for page in GENERATED}}


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
            ("architecture", "components", "component", holds_a_module),
            ("config", "settings", "setting", is_cited)):
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


def is_cited(setting):
    """`C006` matched the setting's name against the lines it cites.

    That is the whole bar, and it is the same one a quoted command clears: the name is
    the part of a configuration row a parser can settle. What the setting *means* is not
    checked by anything, and an answer that goes beyond the name and its default is a
    reading -- `inferred` -- however solid the row behind it.
    """
    return bool(setting.get("evidence"))


def holds_a_module(component):
    """`B003` and `B004` checked these names against the index, and for overlap.

    The weakest of the four, and named so: a component is a grouping decision, and the
    only mechanical thing about it is that the modules exist and belong to it alone.
    """
    return bool(component.get("modules"))


# One `status` used to carry four independent things at once, and collapsing them is
# what let a mechanical result stand in for a judgement: `confirmed` meant both "the
# repository supports this" and "somebody accepted the wording", so passing a schema
# check read as approval. They are separate now.
#
#   basis             how the answer is supported
#   completeness      whether the facets the question asks for are answered
#   content_review    whether a reviewer accepted this exact wording
#   mechanical_checks whether the scripts that can run on it did, and passed
# `asserted` is the one basis with no repository evidence behind it, and it exists because
# refusing it did not make the need go away -- it pushed it out of the document.
#
# A reader needs things the source cannot settle: what a domain term means, what people
# actually ask, what to check first when something fails. `observed`, `declared` and
# `inferred` all require evidence locations, so such an answer could only be `unknown`,
# and `unknown` is not composable. The content therefore had exactly one home, the six
# authored appendix pages, and every generated page had to go without it.
#
# So the boundary moves, and three things keep it honest:
#
#   a name        an asserted answer carries the reviewer who stands behind it, the way
#                 `not_applicable` already does. Nobody asserts anonymously
#   a marker      the rendered paragraph says it is not in the source, and who said it.
#                 A reader can tell this sentence from the ones beside it
#   a ceiling     `ASSERTED_LIMIT` refuses a manual that leans on it. Without that, this
#                 becomes the path of least resistance for every hard question and
#                 rebuilds the failure the evidence rules exist to prevent
BASIS = ("observed", "declared", "inferred", "asserted", "unknown", "not_applicable")
# May be composed into prose a reader sees.
SUBSTANTIVE_BASIS = ("observed", "declared", "inferred", "asserted")
# Must cite repository lines. `asserted` is deliberately absent: requiring evidence of a
# claim whose whole nature is that the repository does not contain it would only push the
# writer into citing something adjacent and calling it support.
EVIDENCE_REQUIRED = ("observed", "declared", "inferred")
COMPLETENESS = ("unanswered", "partial", "complete")
CONTENT_REVIEW = ("pending", "confirmed", "changes_requested", "unresolved")
MECHANICAL_CHECKS = ("not_run", "passed", "failed")


def read_answer(qid, answer, root, origins):
    """One answer checked and normalised. Nothing here is prose a reader will see.

    An answer is a *note*: what the repository says about one template question, with
    what it rests on. The page is composed from these afterwards, so the checks here are
    about whether the note is sound, never about how it reads.
    """
    if not isinstance(answer, dict):
        raise ValueError("%s: answer must be an object" % qid)
    if "status" in answer:
        raise ValueError(
            "%s: `status` is a manual_version 1 field. Version 2 splits it into `basis` "
            "and `completeness`, with review recorded in prose-review.jsonl rather than "
            "asserted here" % qid)
    basis, text = answer.get("basis"), answer.get("text")
    if basis not in BASIS:
        raise ValueError("%s: basis must be one of %s" % (qid, ", ".join(BASIS)))
    completeness = answer.get("completeness")
    if completeness not in COMPLETENESS:
        raise ValueError("%s: completeness must be one of %s"
                         % (qid, ", ".join(COMPLETENESS)))
    if basis in SUBSTANTIVE_BASIS and completeness == "unanswered":
        raise ValueError("%s: an answer with a basis of %r has been answered; "
                         "`unanswered` contradicts it" % (qid, basis))
    if basis in ("unknown", "not_applicable") and completeness != "unanswered":
        raise ValueError("%s: %r carries no answer, so completeness is `unanswered`"
                         % (qid, basis))
    # A writer may say a review has not happened. It may not say one has: the verdict
    # lives in the review channel, bound to the revision it was made against, and
    # trusting a self-set field here is exactly the promotion this split prevents.
    review = answer.get("content_review", "pending")
    if review != "pending":
        raise ValueError(
            "%s: content_review is %r, which only a bound review row may say. An answer "
            "file records `pending`" % (qid, review))
    if not isinstance(text, str) or not text.strip() or text.strip() == "Answer:":
        raise ValueError("%s: answer text is required" % qid)
    evidence = answer.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("%s: evidence must be a list" % qid)
    if basis in EVIDENCE_REQUIRED and not evidence:
        raise ValueError("%s: a basis of %r requires repository evidence. An answer the "
                         "repository cannot support at all is `asserted`, and carries the "
                         "name of whoever stands behind it" % (qid, basis))
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
    # `observed` and `declared` assert the repository settles it, so they carry the same
    # bar `confirmed` carried in v1: something a check could have failed. `inferred` is
    # the model's reading and says so, and needs only its evidence locations.
    if basis in ("observed", "declared") and not verified_ids:
        raise ValueError(
            "%s: a basis of %r must name a verified_id -- a verified claim, a recorded "
            "statement, or a validated procedure, flow, component or setting. An answer "
            "the pipeline never checked has a basis of `inferred`" % (qid, basis))
    if basis == "asserted":
        # A name, because this is the one basis a reader cannot check for themselves. The
        # rendered paragraph prints it, so the accountability reaches the page and not
        # just the notes.
        if not str(answer.get("reviewer", "")).strip():
            raise ValueError(
                "%s: `asserted` names the person who stands behind it. This is the one "
                "answer a reader cannot verify, so it is the one that may not be "
                "anonymous" % qid)
        # No borrowed provenance. An id that a validator passed is evidence, and an answer
        # holding one is `observed`, `declared` or `inferred` -- naming it here would put a
        # check behind a sentence the check never saw.
        if verified_ids:
            raise ValueError(
                "%s: `asserted` cannot name a verified_id (%s). An answer something in "
                "this run actually checked is not an assertion"
                % (qid, ", ".join(sorted(verified_ids)[:3])))
    if basis == "unknown" and not str(answer.get("next_check", "")).strip():
        raise ValueError("%s: unknown requires a concrete next_check" % qid)
    if basis == "not_applicable" and not str(answer.get("reviewer", "")).strip():
        raise ValueError("%s: not_applicable requires reviewer confirmation" % qid)
    # `partial` is a promise about what is missing, and an empty list makes it a label.
    missing = answer.get("facets_missing", [])
    if not isinstance(missing, list) or any(not isinstance(f, str) for f in missing):
        raise ValueError("%s: facets_missing must be a list of strings" % qid)
    if completeness == "partial" and not missing:
        raise ValueError(
            "%s: `partial` must name the facets still missing, or it is `complete` "
            "wearing a hedge" % qid)
    if completeness == "complete" and missing:
        raise ValueError("%s: `complete` cannot also name missing facets: %s"
                         % (qid, ", ".join(missing[:3])))
    return {"id": qid, "basis": basis, "completeness": completeness,
            "content_review": "pending", "text": text, "evidence": evidence,
            "verified_ids": verified_ids, "facets_missing": missing,
            "next_check": answer.get("next_check", ""),
            "reviewer": answer.get("reviewer", "")}


# A run once answered all 161 questions with the same sentence, citing the same line
# range, and every check passed: the count was right, each citation resolved, and
# `A013`/`A014` -- which do catch this on the module side -- are advisory and do not
# reach here at all. One template answer repeated is not 161 answers, and the only
# mechanical tell is that the text does not vary.
#
# The module analysis already flags a near-constant field at 0.95 as a *warning*, because
# a genuinely skewed category is real there. Here it is a failure: 161 questions asking
# different things cannot honestly share one answer, and a manual that shipped them would
# be the questionnaire failure wearing a passing grade.
CONSTANT_ANSWER_LIMIT = 0.30
DUPLICATE_SAMPLE = 3

# How much of a manual may rest on nobody's evidence but a person's word.
#
# This is the load-bearing half of `asserted`. The basis exists because a reader needs
# things the source cannot settle, and that need is real for a minority of the template:
# what a term means, what people ask, what to check first. It is not real for most of it.
# Without a ceiling the basis becomes the answer to every question that turned out to be
# hard to evidence, and a manual of assertions is a manual that documents nobody's
# codebase -- which is the failure the evidence rules exist to prevent, arrived at through
# the door those rules left open.
#
# A fifth is deliberately generous against the handful of questions that genuinely need
# it, and still far from a document that leans on it.
ASSERTED_LIMIT = 0.20


def repeated_answers(notes):
    """Answer texts used for more than `CONSTANT_ANSWER_LIMIT` of the answered set.

    Only answered notes count: a draft's identical `TODO` placeholders are the initializer
    saying nothing yet, which is the honest state and not a duplicate answer.
    """
    answered = [n for n in notes if composable(n)]
    if len(answered) < 4:
        # Too few to tell a repeated template from a short manual.
        return [], len(answered)
    counts = {}
    for note in answered:
        key = " ".join(note["text"].split()).strip().lower()
        counts.setdefault(key, []).append(note["id"])
    repeated = [ids for ids in counts.values()
                if len(ids) > CONSTANT_ANSWER_LIMIT * len(answered)]
    return sorted(repeated, key=len, reverse=True), len(answered)


# Composition is the one step in this pipeline with no floor under it. `read_section`
# enforces exactly one direction -- a section may not cite more than its answers -- and
# narrowing to nothing is permitted by design. So every gate here asks "is this claim
# supported?" and none asks "is this all you had?", which is why a run can answer all 161
# questions honestly and ship twenty three-word pages reporting `answer_mode: answered`.
#
# Measured: nine answers, each with distinct text and real evidence, composed into one
# section reading "It works." -- `validate` clean, `uncomposed` zero, top answer tier, and
# a rendered page of nineteen words, seventeen of them citations.
#
# WORDS PER ANSWER IS THE ONLY BLOCKING MEASURE, and the floor is low. Two other measures
# were tried against real sections and both failed:
#
#   A ratio to the answers' own length is unsound in principle. Compression is what
#   composition IS, so good editing and discard are the same number: a well-written
#   67-word paragraph built from 1400 words of notes retains 4.8%, and the stub that
#   replaced nine answers with "It works." retains 4.1%. It is also gameable from the
#   wrong end -- write terse notes and a terse section clears it -- which would reward the
#   run that read the least. Kept as a reported figure, never a verdict.
#
#   Term overlap between a section and its answers is legitimate to lose: a section may
#   paraphrase completely. Reported, never a verdict.
#
# Calibration, from sections measured rather than imagined:
#   "It works." over 9 answers          0.3 words/answer   <- the failure being stopped
#   a terse but real 2-answer section   7.5
#   a proper 7-answer paragraph         9.6
# A floor of 4 sits an order of magnitude above the stub and well below honest prose. It
# will not catch forty words of filler over nine answers; nothing mechanical will, and the
# prose review queue is where that is somebody's judgement rather than a threshold.
MIN_WORDS_PER_ANSWER = 4
# A term long enough to be about the subject rather than about English.
TERM_LENGTH = 5


def words(text):
    return [w for w in str(text or "").split() if w]


def terms(text):
    """Distinctive lowercase words, for asking whether a section is about its answers."""
    return {w.strip(".,;:()[]\"'`").lower() for w in words(text)
            if len(w.strip(".,;:()[]\"'`")) >= TERM_LENGTH}


def composition_health(body, cited_notes):
    """How much of what the answers held reached the reader, as numbers and complaints.

    Returns the measurements either way. A section is not refused here -- `build` still
    produces it, because a thin draft that renders is reviewable and a build that refuses
    leaves nothing to look at. The verdict is the gate's, on the same render-then-hold
    pattern as P4, the prose queue and the authored ledger.
    """
    body_words = len(words(body))
    answer_words = sum(len(words(n["text"])) for n in cited_notes)
    per_answer = body_words / float(len(cited_notes)) if cited_notes else 0.0
    retained = body_words / float(answer_words) if answer_words else 1.0
    shared = terms(body) & set().union(*[terms(n["text"]) for n in cited_notes]) \
        if cited_notes else set()
    problems = []
    if per_answer < MIN_WORDS_PER_ANSWER:
        problems.append(
            "covers %d question(s) in %d word(s) (%.1f per question, floor %d) -- a "
            "section this short did not compose its answers, it replaced them"
            % (len(cited_notes), body_words, per_answer, MIN_WORDS_PER_ANSWER))
    return {"body_words": body_words, "answer_words": answer_words,
            "words_per_answer": round(per_answer, 1),
            # Both reported, neither a verdict -- see the calibration note above for why
            # each one failed as a threshold. They are here so a reviewer can see the
            # shape of a section without re-deriving it, and so a future floor can be set
            # from recorded runs instead of from a guess.
            "retained": round(retained, 3), "shared_terms": len(shared),
            "problems": problems}


# A section may say that it really is that short, and why. Two things make that an answer
# rather than a way out:
#
#   a name and a reason, both required. "Short" is a label; a reason says what about this
#   subject needs no more words, and who decided that
#
#   a ceiling, for the same reason `asserted` has one and a sharper one. An override with
#   no limit does not soften the retention floor, it deletes it -- every section claims the
#   exception and the check that refuses a stub stops refusing anything. The floor was
#   calibrated against measured sections and nothing honest came within twice it, so an
#   exception should be rare by construction; a quarter of the sections is already far more
#   than "rare" and is where this stops being believable.
BREVITY_LIMIT = 0.25
BREVITY_REASON_WORDS = 5


def read_brevity(where, section):
    """A validated brevity exception for this section, or None. Raises on a malformed one.

    Recorded, never invisible: the block keeps it, the report counts it, and what it
    excused is kept beside it rather than discarded. An exception nobody can see afterwards
    is indistinguishable from a check that was never there.
    """
    brevity = section.get("brevity")
    if brevity is None:
        return None
    if not isinstance(brevity, dict):
        raise ValueError("%s: brevity must be an object with a reason and a reviewer"
                         % where)
    reason = str(brevity.get("reason") or "").strip()
    reviewer = str(brevity.get("reviewer") or "").strip()
    if not reviewer:
        raise ValueError("%s: a brevity exception names the reviewer who accepted it"
                         % where)
    if len(words(reason)) < BREVITY_REASON_WORDS:
        raise ValueError(
            "%s: a brevity exception needs a reason of at least %d words saying what "
            "about this subject needs no more of them. %r is a label"
            % (where, BREVITY_REASON_WORDS, reason[:40]))
    return {"reason": reason, "reviewer": reviewer}


def composable(note):
    """Whether this note may be written into prose a reader sees.

    Basis decides it, not review: a draft is rendered *so that* it can be reviewed, so
    requiring review first would leave nothing to review. `unanswered` is excluded
    because there is no answer to compose, whatever its basis.
    """
    return (note["basis"] in SUBSTANTIVE_BASIS
            and note["completeness"] != "unanswered")


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
        if not composable(note):
            raise ValueError(
                "%s: names %s, whose basis is %s and completeness %s -- an unanswered "
                "or excluded question is reported, never composed into prose"
                % (where, qid, note["basis"], note["completeness"]))
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
    # One reading among the notes makes the section a reading: composition cannot
    # launder an interpretation into an observation by surrounding it with facts. One
    # assertion outranks even that, because it is the only basis with nothing cited under
    # it -- a section holding one cannot honestly be presented as either.
    if any(n["basis"] == "asserted" for n in cited_notes):
        basis = "asserted"
    elif any(n["basis"] == "inferred" for n in cited_notes):
        basis = "inferred"
    else:
        basis = "observed"
    # And one partial note leaves the section partial, for the same reason.
    completeness = "partial" if any(n["completeness"] == "partial" for n in cited_notes) \
        else "complete"
    if basis == "observed" and not verified_ids:
        raise ValueError("%s: an observed section keeps the verified_id its answers "
                         "stand on" % where)
    # The body is authored for the reader. Basis and provenance stay structured so the
    # checker can enforce them without leaking pipeline labels into the manual.
    text = body.strip()
    citations = sorted({citation(e) for e in evidence})
    if citations:
        text += "\n\nSource code: " + "; ".join(citations)
    # An asserted section gets a provenance line where a cited one gets its citations, and
    # for the same reason: a reader is owed where a sentence comes from. This is not the
    # `Inferred:` prefix that was removed -- that was a pipeline label on prose a reader
    # could already check for themselves. Here there is nothing to check, so naming the
    # person is the only provenance there is, and withholding it would leave an unbacked
    # paragraph indistinguishable from the evidenced ones around it.
    asserters = sorted({n["reviewer"] for n in cited_notes
                        if n["basis"] == "asserted" and n["reviewer"]})
    if asserters:
        text += ("\n\nNot documented in the source; stated by %s."
                 % ", ".join(asserters))

    # The retention measurements, and the exception if this section claims one. What the
    # exception excused is kept under `excused` rather than dropped: the gate counts the
    # sections that used one, and a reviewer can see what would otherwise have held the
    # draft. Only the blocking problem is excused -- the reported figures are untouched.
    composed_health = composition_health(body, cited_notes)
    brevity = read_brevity(where, section)
    if brevity:
        composed_health["brevity"] = brevity
        composed_health["excused"] = composed_health["problems"]
        composed_health["problems"] = []
    slug = "%s:%d" % (page_id, order)
    return [
        {"id": "heading:" + slug, "type": "subheading", "text": heading.strip()},
        {"id": "section:" + slug, "type": "prose", "text": text,
         "manual_block": True, "manual_answers": sorted(n["id"] for n in cited_notes),
         "answer_basis": basis, "answer_completeness": completeness,
         "content_review": "pending", "evidence": evidence,
         "composition": composed_health,
         "facets_missing": sorted({f for n in cited_notes for f in n["facets_missing"]}),
         "claim_refs": [r for r in verified_ids if origins.get(r) == "claim"],
         "analysis_refs": [r for r in verified_ids if origins.get(r) == "statement"],
         "verified_by": [{"id": r, "source": origins[r]} for r in sorted(verified_ids)]}]


def gaps_blocks(page_id, notes, composed):
    """What the page could not say, in one place rather than scattered through it.

    A reader is owed the absences, and the run is held back by them -- but an unanswered
    question is a note about the document, not a section of it. Collecting them under one
    marked block keeps the prose readable without letting a gap go unreported.
    """
    unknown = [n for n in notes.values() if n["basis"] == "unknown"]
    excluded = [n for n in notes.values() if n["basis"] == "not_applicable"]
    uncomposed = [n for n in notes.values()
                  if composable(n) and n["id"] not in composed]
    if not (unknown or excluded or uncomposed):
        return []
    parts = []
    if unknown:
        parts.append("The available repository evidence does not yet establish %d "
                     "detail(s) covered by this page." % len(unknown))
    if excluded:
        parts.append("%d template item(s) do not apply to this repository." % len(excluded))
    if uncomposed:
        parts.append("%d answered detail(s) still need to be incorporated into the "
                     "reader-facing explanation." % len(uncomposed))
    return [
        {"id": "heading:gaps:" + page_id, "type": "subheading", "text": "Limitations"},
        {"id": "gaps:" + page_id, "type": "prose", "text": " ".join(parts),
         "absence": True},
    ]


def build(index, content, diagrams, root, claims=(), analysis=None, extra=None):
    if isinstance(content, dict) and content.get("manual_version") == 1:
        raise ValueError(
            "manual-analysis.json is manual_version 1. Version 2 separates basis, "
            "completeness and review, and a v1 `confirmed` cannot be carried across as "
            "approval nobody gave. Migrate it rather than relabelling it")
    if not isinstance(content, dict) or content.get("manual_version") != MANUAL_VERSION:
        raise ValueError("manual requires --manual-analysis with manual_version %d"
                         % MANUAL_VERSION)
    if not index.get("index_hash") or content.get("index_hash") != index["index_hash"]:
        raise ValueError("manual analysis is missing its scan identity or is stale")
    answers = content.get("answers")
    expected = {q["id"] for p in GENERATED for q in p["questions"]}
    if not isinstance(answers, dict) or set(answers) != expected:
        raise ValueError("manual answers must contain exactly every template question ID")
    composed_pages = content.get("pages") or {}
    if not isinstance(composed_pages, dict):
        raise ValueError("manual `pages` must be a map of page id to its sections")
    unknown_pages = set(composed_pages) - {p["id"] for p in GENERATED}
    if unknown_pages:
        raise ValueError("manual `pages` names %s, which the template does not have"
                         % ", ".join(sorted(unknown_pages)[:3]))
    origins = confirmable(claims, analysis, extra)
    cited, unresolved, uncomposed, missing_diagrams = set(), [], [], []
    pages, root = [], Path(root).resolve()

    # Before any page is built: one sentence repeated across the template is not a set of
    # answers, and every other check here passes on it.
    all_notes = [read_answer(q["id"], answers[q["id"]], root, origins)
                 for page in GENERATED for q in page["questions"]]
    repeated, answered_total = repeated_answers(all_notes)
    if repeated:
        worst = repeated[0]
        raise ValueError(
            "%d of %d answered question(s) share one answer (%s%s). Questions asking "
            "different things cannot share an answer; this is a template repeated, not a "
            "manual written"
            % (len(worst), answered_total, ", ".join(worst[:DUPLICATE_SAMPLE]),
               ", ..." if len(worst) > DUPLICATE_SAMPLE else ""))

    # And before any page is built: a manual that rests mostly on assertions documents
    # nobody's codebase. The basis is for the minority of questions the source cannot
    # settle, and the ceiling is what keeps it that.
    asserted = [n["id"] for n in all_notes if n["basis"] == "asserted"]
    if answered_total and len(asserted) > ASSERTED_LIMIT * answered_total:
        raise ValueError(
            "%d of %d answered question(s) are `asserted` -- above the %.0f%% ceiling. "
            "That basis carries no repository evidence, so a manual leaning on it is not "
            "documenting this repository. Evidence the ones that can be evidenced (%s%s)"
            % (len(asserted), answered_total, ASSERTED_LIMIT * 100,
               ", ".join(sorted(asserted)[:DUPLICATE_SAMPLE]),
               ", ..." if len(asserted) > DUPLICATE_SAMPLE else ""))

    for order, spec in enumerate(GENERATED, 1):
        notes = {q["id"]: read_answer(q["id"], answers[q["id"]], root, origins)
                 for q in spec["questions"]}
        unresolved.extend(n["id"] for n in notes.values() if n["basis"] == "unknown")
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
                          if composable(n) and n["id"] not in composed)
        blocks.extend(gaps_blocks(spec["id"], notes, composed))
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
    # The review belongs at the end of the appendix, not ahead of Getting Started -- and
    # the authored pages belong where the template puts them, which is before it.
    places = template_order()
    pages.sort(key=lambda page: places[page["id"]])
    for page in pages:
        page["order"] = places[page["id"]]
    # Carry the cited rows, not every row: a reference has to resolve inside the
    # document it is written in, and shipping the whole claim set would put material on
    # the page that no answer stands on.
    by_claim = {c.get("id"): c for c in claims or ()}
    by_statement = getattr(analysis, "by_id", {})
    by_source = {}
    for ref in cited:
        by_source.setdefault(origins[ref], []).append(ref)
    sections_written = sum(1 for p in pages for b in p["blocks"] if b.get("manual_block"))
    # One figure for how much of what was answered reached a reader, beside the figure for
    # how much was answered. A manual can be complete on the second and empty on the first.
    written = [b for p in pages for b in p["blocks"] if b.get("manual_block")]
    thin = [{"page": p["id"], "block": b["id"],
             "problems": b["composition"]["problems"]}
            for p in pages for b in p["blocks"]
            if b.get("manual_block") and b["composition"]["problems"]]
    body_total = sum(b["composition"]["body_words"] for b in written)
    answer_total = sum(b["composition"]["answer_words"] for b in written)
    # A brevity exception is rare or it is not an exception. Past the ceiling the override
    # has stopped softening the retention floor and started replacing it.
    excused = [{"page": p["id"], "block": b["id"],
                "reviewer": b["composition"]["brevity"]["reviewer"],
                "reason": b["composition"]["brevity"]["reason"],
                "excused": b["composition"]["excused"]}
               for p in pages for b in p["blocks"]
               if b.get("manual_block") and b["composition"].get("brevity")]
    if written and len(excused) > BREVITY_LIMIT * len(written):
        raise ValueError(
            "%d of %d section(s) claim a brevity exception -- above the %.0f%% ceiling. An "
            "exception that common is not an exception; it is the retention floor removed "
            "one section at a time (%s%s)"
            % (len(excused), len(written), BREVITY_LIMIT * 100,
               ", ".join(e["block"] for e in excused[:DUPLICATE_SAMPLE]),
               ", ..." if len(excused) > DUPLICATE_SAMPLE else ""))
    # Named, not generated -- the way `handbook` treats the same material -- but no longer
    # only named. Each carries its ledger row, so the report can say which are still owed
    # and a scaffold can hand the writer what this run already verified for them.
    authored_rows = authored.ledger(AUTHORED, index, analysis, extra,
                                    (extra or {}).get("authored") or ())
    authored_by_page = {row["page_id"]: row for row in authored_rows}
    mode, settled, authored_total = authored.authored_mode(authored_rows)
    return {"preset": "manual", "pages": pages,
            # `order` comes from the same template map the generated pages use, so the
            # renderer's single sort puts every page where the template says -- the
            # appendix interleaved as written, and the review last of all.
            "authored_pages": [{"id": page["id"], "title": page["title"],
                                "order": places[page["id"]],
                                "status": authored_by_page[page["id"]]["status"]}
                               for page in AUTHORED],
            "authored_ledger": authored_rows,
            "authored_coverage": {"mode": mode, "settled": settled,
                                  "total": authored_total,
                                  "unsettled": authored.unsettled(authored_rows)},
            "claims": [by_claim[i] for i in sorted(cited) if i in by_claim],
            "statements": [by_statement[i] for i in sorted(cited) if i in by_statement],
            "coverage": index.get("coverage", {}),
            "source_revision": (index.get("source") or {}).get("revision"),
            "source_dirty": (index.get("source") or {}).get("dirty"),
            "manual_coverage": {"total": len(expected), "unresolved": unresolved,
                                "uncomposed": uncomposed, "sections": sections_written,
                                "missing_diagrams": missing_diagrams,
                                # Reported even though the ceiling above already refuses an
                                # excess: a manual at fifteen per cent passed, and whoever
                                # reads the report is owed the number rather than the
                                # silence that means it was under a threshold.
                                "asserted": sorted(asserted),
                                "answered": answered_total,
                                "brevity_exceptions": excused,
                                "prose_words": body_total,
                                "answer_words": answer_total,
                                "retained": round(body_total / float(answer_total), 3)
                                if answer_total else None,
                                "thin_sections": thin,
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
            if block.get("answer_basis") not in SUBSTANTIVE_BASIS:
                problems.append("manual contains a section with an invalid status")
            if not block.get("evidence"):
                problems.append("manual contains a section without evidence")
            if not block.get("manual_answers"):
                problems.append("manual contains a section naming no answer")
    # The generated pages in template order, which is the same map `build` sorts by rather
    # than a second statement of the same rule that could disagree with it.
    places = template_order()
    expected_order = sorted((p["id"] for p in GENERATED), key=lambda i: places[i])
    if [p.get("id") for p in pages] != expected_order:
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
    parser.add_argument("--config", help="config-analysis.json")
    # Without these two the reading list is missing its two largest sources, and an
    # end-to-end run showed exactly what that costs: 2 facts offered where 15 existed, all
    # of them configuration settings. `observed` and `declared` each require a
    # `verified_id`, so an answer whose evidence the draft never mentioned cannot be
    # written at that basis at all -- the model has no way to know the id exists, and the
    # honest answer left to it is `inferred` or `unknown`.
    parser.add_argument("--claims", help="claims.verified.jsonl, so verified claims are "
                                         "in the reading list")
    parser.add_argument("--analysis", help="module-analysis.jsonl, so recorded statements "
                                           "are in the reading list")
    parser.add_argument("--authored", help="where to write the authored-page ledger; "
                                           "an existing one is never overwritten")
    args = parser.parse_args()
    index = json.loads(Path(args.index).read_text())
    extra = {}
    for key, path in (("architecture", args.architecture), ("flows", args.flows),
                      ("operations", args.operations), ("config", args.config)):
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

    def _rows(path):
        """JSONL rows carrying this scan's identity, or a refusal naming the mismatch."""
        out = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("index_hash") not in (None, index.get("index_hash")):
                raise SystemExit("FAIL %s holds a row written against %s, the index is %s"
                                 % (path, row.get("index_hash"), index.get("index_hash")))
            out.append(row)
        return out

    class _Statements(object):
        """Just the id map `confirmable` reads, not a second `Analysis`.

        `build_document_model` imports this module, so importing its `Analysis` back would
        be a cycle -- and the reading list needs only the mapping. The authored ledger,
        which does want `of_kind` and `modules`, is left the `None` it had: its evidence is
        recomputed at build time from the real `Analysis`, so nothing is lost by an init
        that offers it less.
        """

        def __init__(self, rows=()):
            self.by_id = {}
            for row in rows:
                for statement in row.get("statements", ()) or ():
                    if isinstance(statement, dict) and statement.get("id"):
                        self.by_id[statement["id"]] = dict(statement,
                                                           path=row.get("path", ""))

    claims = _rows(args.claims) if args.claims else ()
    analysis = _Statements(_rows(args.analysis)) if args.analysis else None
    draft = scaffold(index, extra, claims, analysis)
    # Exclusive creation protects an analysis the agent already wrote.
    with open(args.init, "x", encoding="utf-8") as handle:
        json.dump(draft, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    facts = sum(len(v) for v in draft["facts"].values())
    print("wrote %s: %d unanswered question(s); %d verified fact(s) available to cite"
          % (args.init, len(draft["answers"]), facts))
    # The six pages the run does not answer get their obligation recorded at the same
    # moment the questions it does answer get theirs. Writing this only at build time
    # would leave the first run's report saying six pages are missing with nothing on
    # disk that a person could pick up and fill.
    if args.authored and not Path(args.authored).exists():
        rows = authored.ledger(AUTHORED, index, None, extra)
        authored.dump(rows, args.authored)
        owed = len(authored.unsettled(rows))
        print("wrote %s: %d authored page(s), %d still owed a writer"
              % (args.authored, len(rows), owed))
