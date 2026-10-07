#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/document/template.py
# Regenerate: python3 tools/materialize.py
"""Documentation templates: which outline a document is written against, and whether a
written document follows it. Stdlib only; no network, no package installation.

    python3 template.py --list
    python3 template.py --show manual [--sections ID,...] [--drop ID,...]
    python3 template.py --check PATH
    python3 template.py --use NAME|PATH [--sections ID,...] [--drop ID,...]
                        --note "<the user's choice and why>" --out .docs-build/template.json
    python3 template.py --check-docs DIR (--template PATH | --use NAME|PATH)

**No outline is mandatory.** The built-in manual template is one choice among several, not
the shape every document is forced into. The choices are:

  a graph-driven preset   onboarding, architecture, outside-in, handbook -- fixed pages
                          built from the dependency graph; no questions to answer
  the manual template     the built-in question template, whole or only the sections the
                          user picks with --sections / --drop
  an external template    the user's own outline: a Markdown file of headings with the
                          questions or guidance under each, or JSON in the manual schema

Whichever is chosen is written to one file, `template.json`, which every later stage reads.
A question template is then validated the way the built-in manual always was: every
question answered or recorded as unknown, every section composed and evidenced.

`--check-docs` checks a document that already exists -- the rendered draft, a published
tree, or pages a person wrote -- against a template: which sections are present, which are
empty, which still hold placeholder text, and which reproduce the template's questions as
headings instead of answering them. It never edits the document.

Exit codes: 0 fine, 1 a document does not meet its template, 2 bad input.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

TEMPLATE_VERSION = 1
HERE = Path(__file__).resolve().parent
BUILTIN_MANUAL = HERE / "manual_questions.json"

# The graph-driven presets need no question template: their pages are built from the
# graph and the analyses. They are listed so the choice is made among everything on offer,
# not between "the manual" and "nothing".
PRESETS = {
    "onboarding": "File-by-file tour for someone new: entry points, architecture, flows, "
                  "module reference, navigation.",
    "architecture": "Dense shape for a reader who knows the domain: components, "
                    "dependency ranking, class views, flows.",
    "outside-in": "What it is, how to run it, how it is built, then the inventory. Uses "
                  "the architecture, flow and operations analyses.",
    "handbook": "Fills four pages of an existing getting_started/usage/development tree "
                "and leaves every authored page alone.",
}
MANUAL_SUMMARY = ("Question-driven product manual: getting started, architecture, usage, "
                  "development and appendix pages answered from the source. Pick only the "
                  "sections that apply with --sections or --drop.")

PAGE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*)*$")
RESERVED_IDS = {"index", "genindex", "search", "conf"}
DIAGRAM_KINDS = {"class": "diagram-manifest.json", "data_flow": "flow-diagram-manifest.json"}
NOTE_WORDS = 5


class TemplateError(ValueError):
    """A template that cannot be used, with what is wrong with it."""


def digest(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def slug(text):
    out = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return out or "section"


# ---------------------------------------------------------------------------
# Reading templates
# ---------------------------------------------------------------------------

MARKER = re.compile(r"\s*\(([^()]*)\)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def heading_markers(title):
    """Split `Changelog (authored)` into its title and the markers it carries."""
    markers = {}
    while True:
        hit = MARKER.search(title)
        if not hit:
            break
        body = hit.group(1).strip().lower()
        if body == "authored":
            markers["authored"] = True
        elif body == "review":
            markers["review"] = True
        elif body.startswith("diagram"):
            kind = slug(body.split(":", 1)[1] if ":" in body else "")
            if kind not in DIAGRAM_KINDS:
                raise TemplateError("unknown diagram kind in %r -- use (diagram: class) or "
                                    "(diagram: data flow)" % title)
            markers["diagram"] = kind
        else:
            # Ordinary parentheses in a title, such as "Installation (Linux)", stay.
            break
        title = title[:hit.start()].rstrip()
    return title.strip(), markers


def parse_outline(text):
    """A Markdown outline as template pages.

    Headings are sections. A heading with list items under it is a page whose questions are
    those items; a heading with only prose under it is a page whose question is that prose;
    a heading with neither, and no headings under it, is a page with one implicit question.
    A heading whose only content is further headings groups them, and its title becomes the
    navigation caption and the page-id prefix. A lone top-level heading over everything is
    the document's title, not a group.
    """
    nodes, stack, in_fence = [], [], False
    for raw in text.splitlines():
        if FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = HEADING.match(raw)
        if heading:
            level = len(heading.group(1))
            title, markers = heading_markers(heading.group(2))
            if not title:
                continue
            node = {"level": level, "title": title, "markers": markers, "items": [],
                    "prose": [], "children": []}
            while stack and stack[-1]["level"] >= level:
                stack.pop()
            (stack[-1]["children"] if stack else nodes).append(node)
            stack.append(node)
            continue
        if not stack:
            continue
        item = LIST_ITEM.match(raw)
        current = stack[-1]
        if item:
            current["items"].append(item.group(1).strip())
        elif raw.strip():
            if current["items"] and raw.startswith((" ", "\t")):
                current["items"][-1] += " " + raw.strip()
            else:
                current["prose"].append(raw.strip())
    if not nodes:
        raise TemplateError("the outline has no headings; a template is a list of sections")

    if len(nodes) == 1 and nodes[0]["children"] and not nodes[0]["items"]:
        nodes = nodes[0]["children"]

    pages, groups = [], []

    def walk(node, prefix):
        is_page = bool(node["items"] or node["prose"] or not node["children"]) \
            or node["markers"]
        node_slug = slug(node["title"])
        if node["children"] and not (node["items"] or node["prose"]):
            groups.append([prefix + node_slug + "/", node["title"]])
            for child in node["children"]:
                walk(child, prefix + node_slug + "/")
            return
        if is_page:
            if node["items"]:
                questions = node["items"]
            elif node["prose"]:
                questions = [" ".join(node["prose"])]
            else:
                questions = ["What does a reader need to know about %s?" % node["title"]]
            page = {"id": prefix + node_slug, "title": node["title"],
                    "questions": [{"text": q} for q in questions]}
            page.update(node["markers"])
            pages.append(page)
        for child in node["children"]:
            walk(child, prefix + node_slug + "/")

    for node in nodes:
        walk(node, "")
    for number, page in enumerate(pages, 1):
        for q_number, question in enumerate(page["questions"], 1):
            question["id"] = "%d.%d" % (number, q_number)
    return {"pages": pages, "groups": groups}


def builtin_manual():
    pages = json.loads(BUILTIN_MANUAL.read_text(encoding="utf-8"))
    return {"pages": pages, "groups": [["getting_started/", "Getting Started"],
                                        ["architecture/", "Architecture"],
                                        ["usage/", "Usage"],
                                        ["development/", "Development"],
                                        ["appendix/", "Appendix"]]}


def read_source(source):
    """(kind, name, body, origin_text) for a template name or a path."""
    if source == "manual":
        text = BUILTIN_MANUAL.read_text(encoding="utf-8")
        return "questions", "manual", builtin_manual(), text
    if source in PRESETS:
        return "preset", source, None, source
    path = Path(source)
    if not path.is_file():
        raise TemplateError("%r is neither a built-in choice (%s) nor a template file"
                            % (source, ", ".join(["manual"] + sorted(PRESETS))))
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise TemplateError("%s does not parse as JSON (%s)" % (source, exc))
        if isinstance(data, list):
            data = {"pages": data}
        if not isinstance(data, dict) or "pages" not in data:
            raise TemplateError("%s: a JSON template is a list of pages, or an object with "
                                "`pages`" % source)
        if data.get("kind") == "preset":
            return "preset", data.get("name"), None, text
        body = {"pages": data["pages"], "groups": data.get("groups") or []}
        return "questions", data.get("name") or path.stem, body, text
    if path.suffix.lower() in (".md", ".markdown", ".txt"):
        return "questions", path.stem, parse_outline(text), text
    raise TemplateError("%s: a template file is Markdown (.md) or JSON (.json)" % source)


def select(body, sections=None, drop=None):
    """Keep only the chosen pages. An entry ending in `/` names a whole group."""
    def matches(page_id, wanted):
        return any(page_id == w or (w.endswith("/") and page_id.startswith(w))
                   for w in wanted)

    pages = body["pages"]
    if sections:
        unknown = [w for w in sections
                   if not any(matches(p["id"], [w]) for p in pages)]
        if unknown:
            raise TemplateError("--sections names %s, which the template does not have. "
                                "Run --show to see its page ids" % ", ".join(unknown))
        pages = [p for p in pages if matches(p["id"], sections)]
    if drop:
        unknown = [w for w in drop if not any(matches(p["id"], [w]) for p in pages)]
        if unknown:
            raise TemplateError("--drop names %s, which the template does not have"
                                % ", ".join(unknown))
        pages = [p for p in pages if not matches(p["id"], drop)]
    kept = {p["id"] for p in pages}
    groups = [g for g in body.get("groups") or ()
              if any(page_id.startswith(g[0]) for page_id in kept)]
    return {"pages": pages, "groups": groups}


def validate(body):
    """Structural problems with a question template, as a list of strings."""
    problems = []
    pages = body.get("pages")
    if not isinstance(pages, list) or not pages:
        return ["a template needs at least one page"]
    seen_pages, seen_questions, diagrams, reviews = set(), set(), {}, []
    for number, page in enumerate(pages, 1):
        where = "page %d" % number
        if not isinstance(page, dict):
            problems.append("%s is not an object" % where)
            continue
        page_id = page.get("id")
        if not isinstance(page_id, str) or not PAGE_ID.match(page_id):
            problems.append("%s: id %r must be lowercase words joined by _ or -, with / "
                            "between groups" % (where, page_id))
        elif page_id in RESERVED_IDS or page_id.split("/")[-1] in RESERVED_IDS:
            problems.append("%s: id %r would overwrite a file Sphinx owns" % (where, page_id))
        elif page_id in seen_pages:
            problems.append("%s: id %r is used twice" % (where, page_id))
        seen_pages.add(page_id)
        where = "page %r" % page_id
        if not str(page.get("title") or "").strip():
            problems.append("%s has no title" % where)
        questions = page.get("questions")
        if not isinstance(questions, list) or not questions:
            problems.append("%s has no questions -- say what the section must cover" % where)
            questions = []
        for question in questions:
            if not isinstance(question, dict) or not str(question.get("text") or "").strip():
                problems.append("%s has an empty question" % where)
                continue
            qid = question.get("id")
            if not isinstance(qid, str) or not qid.strip():
                problems.append("%s has a question with no id" % where)
            elif qid in seen_questions:
                problems.append("question id %r is used twice" % qid)
            seen_questions.add(qid)
        kind = page.get("diagram")
        if kind is not None:
            if kind not in DIAGRAM_KINDS:
                problems.append("%s: diagram must be one of %s"
                                % (where, ", ".join(sorted(DIAGRAM_KINDS))))
            elif kind in diagrams:
                problems.append("%s and %r both claim the %s diagram"
                                % (where, diagrams[kind], kind))
            else:
                diagrams[kind] = page_id
        if page.get("review"):
            reviews.append(page_id)
    if len(reviews) > 1:
        problems.append("more than one review page: %s" % ", ".join(reviews))
    if not any(isinstance(p, dict) and not p.get("authored") for p in pages):
        problems.append("every page is authored, so there is nothing for the run to write")
    return problems


def resolve(source, sections=None, drop=None):
    """The template a choice names, validated and ready to record."""
    kind, name, body, origin = read_source(source)
    if kind == "preset":
        if sections or drop:
            raise TemplateError("%s is a preset with fixed pages; --sections and --drop "
                                "apply to question templates" % name)
        if name not in PRESETS:
            raise TemplateError("unknown preset %r" % name)
        return {"template_version": TEMPLATE_VERSION, "kind": "preset", "name": name,
                "source": "built-in"}
    body = select(body, sections, drop)
    problems = validate(body)
    if problems:
        raise TemplateError("the template cannot be used:\n  " + "\n  ".join(problems))
    record = {"template_version": TEMPLATE_VERSION, "kind": "questions", "name": name,
              "source": "built-in" if source == "manual" else source,
              "source_hash": digest(origin),
              "selection": {"sections": list(sections or ()), "drop": list(drop or ())},
              "groups": body.get("groups") or [], "pages": body["pages"]}
    record["template_hash"] = template_hash(record["pages"], record["groups"])
    return record


def template_hash(pages, groups):
    """What identifies a template: its pages and groups, not the file they came from."""
    return digest(json.dumps({"pages": pages, "groups": groups}, sort_keys=True))


def load(path):
    """A recorded template.json, checked again: it is an input like any other."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TemplateError("cannot read %s: %s" % (path, exc))
    if not isinstance(data, dict) or data.get("template_version") != TEMPLATE_VERSION:
        raise TemplateError("%s is not a template_version %d record" % (path, TEMPLATE_VERSION))
    if data.get("kind") == "questions":
        problems = validate(data)
        if problems:
            raise TemplateError("%s: %s" % (path, "; ".join(problems)))
    elif data.get("kind") != "preset":
        raise TemplateError("%s: kind must be `questions` or `preset`" % path)
    return data


# ---------------------------------------------------------------------------
# Checking a written document against a template
# ---------------------------------------------------------------------------

DOC_SUFFIXES = (".rst", ".md", ".txt")
PLACEHOLDER = re.compile(
    r"\b(TODO|TBD|FIXME|XXX)\b|lorem ipsum|not yet answered|<\s*(placeholder|fill[^>]*)\s*>"
    r"|this page is written by a person, not generated", re.I)
MIN_WORDS = 20
RST_UNDERLINE = re.compile(r"^([=\-~^\"'`#*+.:_])\1{2,}\s*$")
MD_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")


def normal(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def headings_and_body(text):
    """(headings, prose word count) of one page, Markdown or reStructuredText."""
    lines = text.splitlines()
    headings, body = [], []
    skip = set()
    for i, line in enumerate(lines):
        md = MD_HEADING.match(line)
        if md:
            headings.append(md.group(1))
            skip.add(i)
            continue
        if i + 1 < len(lines) and line.strip() and RST_UNDERLINE.match(lines[i + 1]) \
                and len(lines[i + 1].strip()) >= len(line.strip()):
            headings.append(line.strip())
            skip.update((i, i + 1))
    in_directive = False
    for i, line in enumerate(lines):
        if i in skip or RST_UNDERLINE.match(line):
            continue
        stripped = line.strip()
        if stripped.startswith(("..", "```", ":::", "{", ":")):
            in_directive = stripped.startswith(("..", "```", ":::"))
            continue
        if in_directive and (line.startswith((" ", "\t")) or not stripped):
            continue
        in_directive = False
        body.append(stripped)
    return headings, len(" ".join(body).split())


def find_page(docs, page):
    """The file that holds this template page: by its id, or by its title as a heading."""
    for suffix in DOC_SUFFIXES:
        candidate = docs / (page["id"] + suffix)
        if candidate.is_file():
            return candidate, None
    wanted = normal(page["title"])
    for path in sorted(docs.rglob("*")):
        if path.suffix not in DOC_SUFFIXES or not path.is_file():
            continue
        if any(part.startswith((".", "_")) for part in path.relative_to(docs).parts):
            continue
        headings, _ = headings_and_body(path.read_text(encoding="utf-8", errors="replace"))
        if any(normal(h) == wanted for h in headings):
            return path, page["title"]
    return None, None


def check_docs(template, docs):
    """Per-page verdicts for a document against a question template."""
    docs = Path(docs)
    if not docs.is_dir():
        raise TemplateError("%s is not a directory" % docs)
    rows = []
    for page in template["pages"]:
        path, by_heading = find_page(docs, page)
        row = {"page": page["id"], "title": page["title"],
               "authored": bool(page.get("authored")), "file": None, "problems": []}
        if path is None:
            row["status"] = "missing"
            row["problems"].append("no page %s.(rst|md) and no heading %r"
                                   % (page["id"], page["title"]))
            rows.append(row)
            continue
        row["file"] = str(path.relative_to(docs))
        text = path.read_text(encoding="utf-8", errors="replace")
        headings, words = headings_and_body(text)
        if by_heading:
            row["problems"].append("found as a heading in %s, not as its own page"
                                   % row["file"])
        placeholder = PLACEHOLDER.search(text)
        if placeholder:
            row["problems"].append("still holds placeholder text %r" % placeholder.group(0))
        asked = {normal(q["text"]) for q in page.get("questions", ())}
        echoed = [h for h in headings if normal(h) in asked]
        if asked and len(echoed) * 2 >= len(asked) and len(asked) > 1:
            row["problems"].append("%d of its %d questions are headings -- the template was "
                                   "copied, not answered" % (len(echoed), len(asked)))
        if not by_heading and words < MIN_WORDS:
            row["problems"].append("has %d word(s) of prose; a section needs at least %d"
                                   % (words, MIN_WORDS))
        row["words"] = words
        blocking = [p for p in row["problems"] if not p.startswith("found as a heading")]
        row["status"] = "incomplete" if blocking else "present"
        rows.append(row)
    owed = [r for r in rows if r["status"] != "present" and not r["authored"]]
    authored_owed = [r for r in rows if r["status"] != "present" and r["authored"]]
    return {"template": template.get("name"), "docs": str(docs),
            "pages": len(rows), "present": sum(r["status"] == "present" for r in rows),
            "owed": [r["page"] for r in owed],
            "authored_owed": [r["page"] for r in authored_owed],
            "passed": not owed and not authored_owed, "rows": rows}


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def split(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def print_choices():
    print("Choices -- none is mandatory; recommend one, and record the user's pick with "
          "--use:\n")
    for name in sorted(PRESETS):
        print("  %-12s preset    %s" % (name, PRESETS[name]))
    pages = builtin_manual()["pages"]
    print("  %-12s template  %s" % ("manual", MANUAL_SUMMARY))
    print("  %-12s template  Your own outline: a Markdown file of headings with the "
          "questions or guidance under each, or JSON in the manual schema." % "<path>")
    print("\nThe manual template's %d sections (--sections / --drop take these ids, or a "
          "group such as appendix/):" % len(pages))
    for page in pages:
        flags = [k for k in ("authored", "review") if page.get(k)]
        if page.get("diagram"):
            flags.append("diagram: %s" % page["diagram"])
        print("  %-40s %-34s %d question(s)%s"
              % (page["id"], page["title"], len(page["questions"]),
                 " [%s]" % ", ".join(flags) if flags else ""))


def show(record):
    if record["kind"] == "preset":
        print("preset %s: %s" % (record["name"], PRESETS[record["name"]]))
        return
    print("template %s: %d page(s), %d question(s)"
          % (record["name"], len(record["pages"]),
             sum(len(p["questions"]) for p in record["pages"])))
    for page in record["pages"]:
        flags = [k for k in ("authored", "review") if page.get(k)]
        if page.get("diagram"):
            flags.append("diagram: %s" % page["diagram"])
        print("  %-40s %s%s" % (page["id"], page["title"],
                                " [%s]" % ", ".join(flags) if flags else ""))
        for question in page["questions"]:
            print("      %-8s %s" % (question["id"], question["text"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="print the choices")
    action.add_argument("--show", metavar="NAME|PATH", help="print one template's outline")
    action.add_argument("--check", metavar="PATH", help="validate a template file")
    action.add_argument("--use", metavar="NAME|PATH", help="record the chosen template")
    action.add_argument("--check-docs", metavar="DIR",
                        help="check a written document against a template")
    parser.add_argument("--sections", help="comma-separated page ids or groups to keep")
    parser.add_argument("--drop", help="comma-separated page ids or groups to leave out")
    parser.add_argument("--template", help="--check-docs: a recorded template.json, or a "
                                           "built-in name or template file")
    parser.add_argument("--note", help="--use: whose choice this is and why")
    parser.add_argument("--out", help="--use: where to write template.json; "
                                      "--check-docs: where to write the report")
    args = parser.parse_args(argv)
    sections, drop = split(args.sections), split(args.drop)

    try:
        if args.list:
            print_choices()
            return 0
        if args.show:
            show(resolve(args.show, sections, drop))
            return 0
        if args.check:
            record = resolve(args.check, sections, drop)
            show(record)
            print("\nOK the template is usable")
            return 0
        if args.use:
            if len(str(args.note or "").split()) < NOTE_WORDS:
                raise TemplateError("--use needs a --note of at least %d words saying who "
                                    "chose this and why -- the choice is the user's, and "
                                    "the report has to be able to say so" % NOTE_WORDS)
            if not args.out:
                raise TemplateError("--use needs --out")
            record = resolve(args.use, sections, drop)
            record["note"] = args.note.strip()
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
            show(record)
            print("\nwrote %s" % args.out)
            return 0
        source = args.template or "manual"
        if Path(source).is_file() and Path(source).suffix == ".json":
            try:
                record = load(source)
            except TemplateError:
                record = resolve(source, sections, drop)
        else:
            record = resolve(source, sections, drop)
        if record["kind"] == "preset":
            raise TemplateError("%s is a preset; its pages are checked by the pipeline's "
                                "own gate, not against a question template" % record["name"])
        report = check_docs(record, args.check_docs)
    except TemplateError as exc:
        sys.stderr.write("FAIL %s\n" % exc)
        return 2

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in report["rows"]:
        print("%-10s %-40s %s" % (row["status"], row["page"],
                                  "; ".join(row["problems"]) or row["file"]))
    print("\n%d of %d template page(s) present and written%s"
          % (report["present"], report["pages"],
             "" if report["passed"] else
             " -- owed: %s" % ", ".join(report["owed"] + report["authored_owed"])))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
