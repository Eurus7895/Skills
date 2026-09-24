#!/usr/bin/env python3
"""Find the passages in a rendered document that a person will struggle to read.

    python3 scripts/publish/readability.py docs
    python3 scripts/publish/readability.py docs --worst 10
    python3 scripts/publish/readability.py docs --format json --out readability.json

Every other check in this skill asks whether the document is *right*: `P003` refuses a
block claiming more than its citations support, `P004` one stating an inference as fact,
the quality gate refuses a section that replaced its answers with nothing. None of them
asks whether a person can read the result, and a manual nobody finishes is a manual that
failed whatever its citations prove.

**This one is standalone on purpose.** It imports nothing from the rest of the pipeline and
reads no build directory, so it runs against a `docs/` tree on a machine that has none of
the other scripts, no index, and no seal. Improving how a document reads is not a step in
the publication lifecycle and should not be blocked by it. The duplication of
`sentence_lengths` from `document/manual.py` is the price of that, and it is worth paying:
a reviewer who cannot run this cannot use it.

**It reports and never refuses.** These measurements describe a shape, and a shape is not a
verdict: a subject can honestly need a long sentence, and a reference table is a wall of
text because that is what a table is. The output names passages worth looking at, in the
order worth looking at them. A person decides.

Exit codes: 0 read the tree, 2 the path is not a directory or holds no pages.

Standard library only. Reads the given directory; writes only `--out`, when given.
"""

import argparse
import json
import os
import re
import sys

# The same number `prose-generation.md` gives as a drafting rule: where a sentence stops
# being one idea and becomes clauses the reader has to hold at once.
LONG_SENTENCE_WORDS = 25

# A paragraph past this has stopped being a paragraph. Scanning is how a reader finds the
# part they came for, and an unbroken block is what stops them.
LONG_PARAGRAPH_SENTENCES = 5

# How many sections must open the same way before it is the form writing the prose rather
# than the subject. Two is a coincidence; three is a template.
REPEATED_OPENING = 3

# The first words of a sentence that announces a section instead of answering it. Matched
# at the start only: "This document describes the configuration" is announcing, while
# "the queue rejects it, which this section describes" is not.
ANNOUNCING = (
    "this section", "this page", "this chapter", "this document", "this guide",
    "this part", "in this section", "in this chapter", "the following", "below you",
    "here we", "we will", "this describes", "this explains", "this covers",
)

SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")
RST_HEADING = re.compile(r"^[=\-~^\"'`#*+_]{3,}\s*$")
MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
DIRECTIVE = re.compile(r"^\s*(\.\.\s|```|:\w+:|\||\+[-=]|\*\s|-\s|\d+\.\s)")


def words(text):
    return [w for w in str(text or "").split() if w]


def sentence_lengths(text):
    """Word counts of each sentence, in the order they appear.

    Crude on purpose. A full stop inside `pipeline.py` or `e.g.` starts a new sentence here,
    and a count one or two out does not change what a reviewer does about a 60-word one.
    """
    body = str(text or "").strip()
    if not body:
        return []
    return [len(words(part)) for part in SENTENCE_END.split(body) if words(part)]


def opening(text):
    """The first few words of a passage, lowercased, for spotting repeated shapes."""
    return " ".join(w.lower().strip(".,;:()[]\"'`") for w in words(text)[:4])


def announces(text):
    """Whether the passage opens by saying what it is about rather than saying it."""
    start = " ".join(words(text)[:4]).lower()
    return any(start.startswith(phrase) for phrase in ANNOUNCING)


def prose_paragraphs(lines):
    """(first line number, text) for each run of prose, skipping markup.

    Directives, tables, code fences, option lines and list items are dropped: a `list-table`
    is not a paragraph, and measuring one as prose reports every reference page as a wall.
    """
    paragraphs, buffer, start = [], [], 0
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or DIRECTIVE.match(line) or RST_HEADING.match(line):
            if buffer:
                paragraphs.append((start, " ".join(buffer)))
                buffer = []
            continue
        if not buffer:
            start = number
        buffer.append(stripped)
    if buffer:
        paragraphs.append((start, " ".join(buffer)))
    return paragraphs


FENCE = re.compile(r"^\s*(```|~~~)")
LITERAL_END = re.compile(r"::\s*$")


def blank_code(lines):
    """The same lines with every code region blanked, so nothing measures a program.

    **Measured before this existed: 257 long sentences across the skill's own references,
    and sections titled `}`.** A JSON body is not prose and an 80-word "sentence" spanning
    a schema block is not a sentence, so every count was noise and the worst-first list --
    the whole point of the report -- was a list of code. A `---` inside a fence was read as
    a reStructuredText heading rule, which made the line above it a section title.

    Three shapes are removed: a MyST fence and everything to its close, a reStructuredText
    literal block (a paragraph ending `::` followed by an indented run), and any indented
    line, which is a directive's content wherever it appears. Blanked rather than dropped,
    so every line number the report prints still points at the right line in the file.
    """
    out, fence, literal = [], None, False
    for line in lines:
        stripped = line.strip()
        opening_fence = FENCE.match(line)
        if fence:
            out.append("")
            if opening_fence and stripped.startswith(fence):
                fence = None
            continue
        if opening_fence:
            fence = opening_fence.group(1)
            out.append("")
            continue
        if literal:
            if not stripped or line[:1].isspace():
                out.append("")
                continue
            literal = False
        if stripped and line[:1].isspace():
            out.append("")
            continue
        out.append(line)
        if LITERAL_END.search(stripped):
            literal = True
    return out


def sections(path):
    """(heading, first line, [(line, paragraph)]) for each section of one page."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = blank_code(fh.read().splitlines())

    marks = []
    for number, line in enumerate(lines):
        heading = MD_HEADING.match(line)
        if heading:
            marks.append((number, heading.group(2).strip()))
        elif RST_HEADING.match(line) and number and lines[number - 1].strip() \
                and not RST_HEADING.match(lines[number - 1]):
            marks.append((number - 1, lines[number - 1].strip()))
    if not marks:
        marks = [(0, os.path.basename(path))]

    found = []
    for position, (start, title) in enumerate(marks):
        end = marks[position + 1][0] if position + 1 < len(marks) else len(lines)
        # Past the heading itself, not from it. A reStructuredText heading is a line of
        # ordinary text over a rule, and the text line is neither blank, a directive nor a
        # rule -- so it was collected as the section's first paragraph, and every question
        # asked about that paragraph was asked about the heading. `announces` compared
        # "Configuration" against "this section ..." and found nothing; `repeated_openings`
        # compared three headings that differ and reported no repetition, on a page whose
        # every section opened "This section describes". Measured on a fixture written to
        # fail: it reported 0 of each.
        body = lines[start + heading_depth(lines, start):end]
        found.append((title, start + 1,
                      [(start + offset, text)
                       for offset, text in prose_paragraphs(body)]))
    return found


def heading_depth(lines, start):
    """How many lines the heading at `start` occupies: 1 for MyST, 2 for RST with a rule."""
    if MD_HEADING.match(lines[start]):
        return 1
    if start + 1 < len(lines) and RST_HEADING.match(lines[start + 1]):
        return 2
    return 0


QUOTE_WORDS = 30


def quote(text):
    """Enough of a passage to judge it by, without reprinting the page."""
    parts = words(text)
    if len(parts) <= QUOTE_WORDS:
        return " ".join(parts)
    return " ".join(parts[:QUOTE_WORDS]) + " ..."


def measure(title, line, paragraphs):
    """What is worth saying about one section, and how much of it there is.

    Each note carries the passage itself, not only where it is. A number is enough to find
    a long sentence and not enough to judge one: whether 30 words are clear or tangled is a
    reading, and the reading is what this cannot do. Quoting the text is what lets the next
    reader -- a person, or a model asked to look -- answer the question this only raises.
    """
    notes, longest, sentence_count = [], 0, 0
    for where, text in paragraphs:
        lengths = sentence_lengths(text)
        sentence_count += len(lengths)
        for length in lengths:
            longest = max(longest, length)
            if length > LONG_SENTENCE_WORDS:
                notes.append({"line": where, "kind": "long_sentence", "value": length,
                              "text": quote(text),
                              "detail": "a %d-word sentence: one idea per sentence, and "
                                        "under %d words" % (length, LONG_SENTENCE_WORDS)})
        if len(lengths) > LONG_PARAGRAPH_SENTENCES:
            notes.append({"line": where, "kind": "long_paragraph", "value": len(lengths),
                          "text": quote(text),
                          "detail": "a %d-sentence paragraph: a block this long is one "
                                    "nobody scans" % len(lengths)})
    if paragraphs and announces(paragraphs[0][1]):
        notes.append({"line": paragraphs[0][0], "kind": "announces", "value": 1,
                      "text": quote(paragraphs[0][1]),
                      "detail": "opens by saying what the section is about. Lead with the "
                                "answer instead -- the heading already said the subject"})
    return {"section": title, "line": line, "paragraphs": len(paragraphs),
            "sentences": sentence_count, "longest_sentence": longest, "notes": notes}


def repeated_openings(measured, paragraphs_by_section):
    """Sections in a row that begin the same way, which is the form writing the prose."""
    found, run, shape = [], [], None
    order = [(m["section"], paragraphs_by_section.get(m["section"])) for m in measured]
    for title, first in order + [(None, None)]:
        current = opening(first) if first else None
        if current and current == shape:
            run.append(title)
            continue
        if shape and len(run) >= REPEATED_OPENING:
            found.append({"opening": shape, "sections": list(run)})
        shape, run = current, [title] if current else []
    return found


def pages(root):
    found = []
    for base, _, names in os.walk(root):
        for name in sorted(names):
            if name.endswith((".rst", ".md")):
                found.append(os.path.join(base, name))
    return sorted(found)


def report(root):
    result = {"readability_version": 1, "docs": root, "pages": [],
              "long_sentence_words": LONG_SENTENCE_WORDS}
    for path in pages(root):
        measured, firsts = [], {}
        for title, line, paragraphs in sections(path):
            if not paragraphs:
                continue
            measured.append(measure(title, line, paragraphs))
            firsts[title] = paragraphs[0][1]
        if not measured:
            continue
        result["pages"].append({
            "path": os.path.relpath(path, root),
            "sections": measured,
            "repeated_openings": repeated_openings(measured, firsts)})
    totals = [note for page in result["pages"] for section in page["sections"]
              for note in section["notes"]]
    sentences = sum(s["sentences"] for p in result["pages"] for s in p["sections"])
    result["counts"] = {
        "pages": len(result["pages"]),
        "sections": sum(len(p["sections"]) for p in result["pages"]),
        # Reported beside the count because the count alone is unreadable in both
        # directions: 232 sounds like a crisis and is 26% of a dense reference set, while
        # 12 on a short page can be most of it. Measured on this skill's own references,
        # which run at 26% -- so a document at that rate is ordinary technical prose, and
        # one at 60% is where the shape itself is the problem.
        "sentences": sentences,
        "long_sentence_share": round(
            len([n for n in totals if n["kind"] == "long_sentence"]) / float(sentences), 3)
        if sentences else 0.0,
        "long_sentences": sum(1 for n in totals if n["kind"] == "long_sentence"),
        "long_paragraphs": sum(1 for n in totals if n["kind"] == "long_paragraph"),
        "announcing_openings": sum(1 for n in totals if n["kind"] == "announces"),
        "repeated_openings": sum(len(p["repeated_openings"]) for p in result["pages"]),
    }
    return result


def worst_first(result, limit):
    """The passages to look at, hardest first, because a list nobody finishes is no use."""
    rows = []
    for page in result["pages"]:
        for section in page["sections"]:
            for note in section["notes"]:
                rows.append((note["value"], page["path"], note["line"],
                             section["section"], note["detail"],
                             note.get("text", "")))
    rows.sort(key=lambda row: -row[0])
    return rows[:limit]


def render(result, limit):
    counts = result["counts"]
    print("%d page(s), %d section(s), %d sentence(s)"
          % (counts["pages"], counts["sections"], counts["sentences"]))
    print("  %d over %d words (%.0f%% -- dense technical reference prose runs about 26%%)"
          % (counts["long_sentences"], result["long_sentence_words"],
             100 * counts["long_sentence_share"]))
    print("  %d paragraph(s) over %d sentences" % (counts["long_paragraphs"],
                                                   LONG_PARAGRAPH_SENTENCES))
    print("  %d section(s) opening by announcing themselves"
          % counts["announcing_openings"])
    print("  %d run(s) of %d+ sections opening the same way"
          % (counts["repeated_openings"], REPEATED_OPENING))

    rows = worst_first(result, limit)
    if rows:
        print("\nworst first:")
        for _, path, line, section, detail, text in rows:
            print("  %s:%d  [%s]\n      %s" % (path, line, section, detail))
            if text:
                print("      > %s" % text)

    for page in result["pages"]:
        for run in page["repeated_openings"]:
            print("\n%s: %d sections open \"%s ...\"\n      %s"
                  % (page["path"], len(run["sections"]), run["opening"],
                     ", ".join(run["sections"])))

    if not rows and not counts["repeated_openings"]:
        print("\nNothing stood out. That is a statement about sentence and paragraph "
              "shape,\nnot about whether the document explains anything.")


REVIEW_PREAMBLE = """\
These passages were flagged by shape alone -- sentence length, paragraph length, a repeated
opening. Shape is a signal and not a verdict, and the questions below are the ones no
measurement can answer. Read each passage and say, for each one:

  1. Is it clear as it stands? A long sentence can be perfectly clear, and a short one can
     be impenetrable. If it is clear, say so and move on.
  2. If it is not, what is wrong: too much in one sentence, an undefined term, or steps in
     an order the reader cannot follow?
  3. Give the replacement, not a note asking for one.

Two things this could not check at all, so look for them while you are here: a term used
before it is defined, and a procedure given out of order.
"""


def for_review(result, limit):
    """The flagged passages, framed for whoever reads them next.

    **The measurement and the judgement are different jobs, and this is the join.** What the
    script finds is shape; whether a 30-word sentence is tangled or merely long is a reading.
    Handing over the passages with the questions attached is what turns a list of line
    numbers into something a person -- or a model asked to look -- can act on, and it keeps
    the reading bounded: the whole document is too much to review honestly, and fifteen
    passages is not.
    """
    lines = [REVIEW_PREAMBLE]
    for position, row in enumerate(worst_first(result, limit), 1):
        _, path, line, section, detail, text = row
        lines.append("%d. %s:%d  [%s]\n   %s\n   > %s"
                     % (position, path, line, section, detail, text or "(no text)"))
    if len(lines) == 1:
        lines.append("Nothing was flagged by shape. The two questions above still stand, "
                     "and\nnothing here has looked at them.")
    return "\n\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("docs", help="the rendered documentation directory")
    parser.add_argument("--worst", type=int, default=15,
                        help="how many passages to list (default 15)")
    parser.add_argument("--for-review", action="store_true",
                        help="print the flagged passages with the questions a reader or "
                             "model should answer about them")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--out", help="also write the full report here, as JSON")
    args = parser.parse_args()

    if not os.path.isdir(args.docs):
        sys.stderr.write("FAIL  not a directory: %s\n" % args.docs)
        return 2
    result = report(args.docs)
    if not result["pages"]:
        sys.stderr.write("FAIL  no .rst or .md page with prose in it under %s\n"
                         % args.docs)
        return 2

    if args.for_review:
        print(for_review(result, args.worst))
    elif args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        render(result, args.worst)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")
        if args.format != "json":
            print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
