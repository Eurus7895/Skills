#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/build_document_model.py
# Regenerate: python3 tools/materialize.py
"""Organise verified claims into a format-independent document model.

    python3 scripts/build_document_model.py --index structure.json \\
        --claims .docs-build/claims.verified.jsonl \\
        --fragments .docs-build/fragments.verified.jsonl \\
        --preset onboarding --out .docs-build/doc.json

`doc.json` is pages and blocks, with no RST or Markdown in it. Which pages exist and
which are mandatory is the preset's decision and is deterministic; what they say comes
from the verified fragments. Renderers turn this into one markup or another, and a page
that cannot be rendered from this file is a page whose content was never verified.

What may appear where, and why:

    verified             a fact, stated plainly
    supported_inference  a reading of the code, labelled as one
    candidate            named in Limitations only, never in prose
    unsupported          named in Limitations only -- undecidable in principle
    needs_context        named in Limitations only, never in prose
    rejected             never rendered at all; its presence fails the build

That table is the whole point of the pipeline. A candidate claim printed in a paragraph
is indistinguishable to a reader from a verified one, so the boundary is enforced here
rather than left to whoever writes the sentence.

Exit codes: 0 written, 1 the model is not valid, 2 input/schema error, 3 internal error.

Standard library only. Reads its inputs; writes only --out.
"""

import argparse
import json
import os
import sys

FORMAT_VERSION = 1
GENERATOR_VERSION = "0.2.0-dev"
SUPPORTED_SCHEMA = {2}

PROSE_STATUSES = ("verified", "supported_inference")
LIMITATION_STATUSES = ("candidate", "unsupported", "needs_context")

# A preset fixes the skeleton: which pages exist, in what order, and which of them may
# not be dropped. It says nothing about what is true -- that comes from the claims.
PRESETS = {
    "onboarding": [
        ("overview", "Overview", True),
        ("entry-points", "Entry points", True),
        ("architecture", "Architecture", True),
        ("flows", "Important flows", True),
        ("modules", "Module reference", True),
        ("navigation", "Finding your way around", True),
        ("limitations", "Coverage and limitations", True),
    ],
    # No module reference here by design: this preset is for a reader who already knows
    # the domain and wants the shape, not the inventory.
    "architecture": [
        ("overview", "Architecture overview", True),
        ("architecture", "Components and boundaries", True),
        ("dependencies", "Dependency graph", True),
        ("class-views", "Classes and inheritance", True),
        ("flows", "Cross-component flows", True),
        ("limitations", "Coverage and limitations", True),
    ],
}


def load_rows(path, label):
    if not os.path.isfile(path):
        return None, "no such %s file: %s" % (label, path)
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    return None, "%s line %d: %s" % (path, number, exc)
                rows.append(row)
    except OSError as exc:
        return None, "cannot read %s: %s" % (path, exc)
    return rows, None


def prose(block_id, text, claim_refs=()):
    return {"id": block_id, "type": "prose", "text": text,
            "claim_refs": sorted(claim_refs)}


def table(block_id, columns, rows, claim_refs=()):
    return {"id": block_id, "type": "table", "columns": list(columns),
            "rows": [list(r) for r in rows], "claim_refs": sorted(claim_refs)}


def cite(path, line):
    return "%s:%d" % (path, line)


def overview_page(index, fragments, claims_by_id):
    coverage = index.get("coverage", {})
    languages = ", ".join("%s (%d)" % (lang, count) for lang, count
                          in sorted(coverage.get("languages", {}).items(),
                                    key=lambda kv: -kv[1]))
    revision = (index.get("source") or {}).get("revision")
    blocks = [prose("block:overview-scope",
                    "This document describes %d source file(s) written in %s, scanned "
                    "at revision %s. Every structural statement below cites the file "
                    "and line it was read from."
                    % (coverage.get("files_scanned", 0), languages or "no known language",
                       revision or "an untracked working tree"))]

    # Whatever the fragments say about the most depended-upon modules is the closest
    # thing to a summary that is actually backed by something.
    fan_in = index.get("fan_in", {})
    ranked = sorted(fragments, key=lambda f: -fan_in.get(f.get("source", ""), 0))
    top = [f for f in ranked if f.get("status") in PROSE_STATUSES][:5]
    if top:
        blocks.append(table(
            "block:overview-key-modules",
            ("Module", "Depended on by", "Role"),
            [(f["source"], str(fan_in.get(f["source"], 0)), f.get("role", ""))
             for f in top],
            {c for f in top for c in f.get("claim_ids", ())
             if claims_by_id.get(c, {}).get("status") in PROSE_STATUSES}))
    return blocks


def entry_points_page(index):
    rows = [(e["path"], e["reason"].replace("_", " ")) for e in index.get("entry_points", ())]
    if not rows:
        return [prose("block:entry-points-none",
                      "No file in this repository both goes unimported and looks like a "
                      "way in. That is normal for a library.")]
    return [
        prose("block:entry-points-intro",
              "Nothing in the repository imports these files, and each either carries a "
              "main guard or is named by convention as a way in."),
        table("block:entry-points", ("Path", "Identified by"), rows),
    ]


def architecture_page(index, claims_by_id):
    edges = [e for e in index.get("edges", ())
             if os.path.dirname(e["from"]) != os.path.dirname(e["to"])]
    verified_imports = {
        (c["subject"].split(":", 1)[1], c["object"].split(":", 1)[1]): c["id"]
        for c in claims_by_id.values()
        if c.get("kind") == "imports" and c.get("status") == "verified"
        and isinstance(c.get("subject"), str) and isinstance(c.get("object"), str)}

    blocks = [prose("block:architecture-intro",
                    "Each row is an import edge that crosses a directory boundary -- the "
                    "places where one part of the tree reaches into another. An import "
                    "proves a reference, not a call.")]
    if edges:
        rows, refs = [], set()
        for edge in edges:
            claim_id = verified_imports.get((edge["from"], edge["to"]))
            rows.append((edge["from"], edge["to"], cite(edge["from"], edge["line"])))
            if claim_id:
                refs.add(claim_id)
        blocks.append(table("block:architecture-edges",
                            ("From", "Imports", "At"), rows, refs))
    else:
        blocks.append(prose("block:architecture-flat",
                            "No import crosses a directory boundary in this repository."))
    return blocks


def dependencies_page(index):
    fan_in = index.get("fan_in", {})
    ranked = sorted(fan_in.items(), key=lambda kv: (-kv[1], kv[0]))[:25]
    if not ranked:
        return [prose("block:dependencies-none",
                      "No file in this repository imports another.")]
    return [
        prose("block:dependencies-intro",
              "Ranked by how many modules in this repository import each file."),
        table("block:dependencies", ("Path", "Imported by"),
              [(path, str(count)) for path, count in ranked]),
    ]


def modules_page(index, fragments, claims_by_id):
    fan_in = index.get("fan_in", {})
    rows, refs = [], set()
    for fragment in sorted(fragments, key=lambda f: f.get("source", "")):
        if fragment.get("status") not in PROSE_STATUSES:
            continue
        rows.append((fragment["source"], str(fan_in.get(fragment["source"], 0)),
                     fragment.get("role", "")))
        refs.update(c for c in fragment.get("claim_ids", ())
                    if claims_by_id.get(c, {}).get("status") in PROSE_STATUSES)
    if not rows:
        return [prose("block:modules-none",
                      "No module description survived verification. Nothing is stated "
                      "here rather than stating something unchecked.")]
    return [
        prose("block:modules-intro",
              "One row per module whose description was verified against the graph."),
        table("block:modules", ("Path", "Imported by", "Role"), rows, refs),
    ]


def flows_page(index, claims_by_id):
    """Call chains, built only from calls that were verified at their call site.

    An import edge would give a much fuller-looking picture and would be a different,
    weaker claim. A flow assembled from imports says "these files reference each other",
    which is not what a reader takes "the request passes through here" to mean.
    """
    calls = [c for c in claims_by_id.values()
             if c.get("kind") == "calls" and c.get("status") == "verified"
             and isinstance(c.get("subject"), str) and isinstance(c.get("object"), str)]
    if not calls:
        return [prose("block:flows-none",
                      "No call was verified at its call site, so no flow is described "
                      "here. Import relationships appear under Architecture; they show "
                      "which modules reference each other, not what calls what.")]

    rows, refs = [], set()
    for claim in sorted(calls, key=lambda c: c["id"]):
        caller = claim["subject"].split(":", 1)[1]
        target = claim["object"]
        evidence = (claim.get("evidence") or [{}])[0]
        where = evidence.get("path"), evidence.get("line_start")
        rows.append((caller, target.split(":", 1)[1],
                     cite(where[0], where[1]) if where[0] and where[1] else "-"))
        refs.add(claim["id"])
    return [
        prose("block:flows-intro",
              "Each row is a call read at the line cited, not inferred from an import. "
              "Anything the verifier could not confirm at its call site is listed under "
              "Coverage and limitations instead."),
        table("block:flows", ("From", "Calls", "At"), rows, refs),
    ]


def navigation_page(index):
    """Where to start reading, from the directory grouping and the entry points."""
    grouped = {}
    for record in index.get("files", ()):
        grouped.setdefault(os.path.dirname(record["path"]) or ".", []).append(record)

    fan_in = index.get("fan_in", {})
    rows = []
    for directory, records in sorted(grouped.items()):
        busiest = max(records, key=lambda r: fan_in.get(r["path"], 0))
        rows.append((directory, str(len(records)),
                     busiest["path"] if fan_in.get(busiest["path"]) else "-"))

    blocks = [
        prose("block:navigation-intro",
              "The repository grouped by directory. The third column is the file in each "
              "directory that the most other modules import -- usually the one to read "
              "first."),
        table("block:navigation-clusters",
              ("Directory", "Files", "Most depended upon"), rows),
    ]
    entries = index.get("entry_points", ())
    if entries:
        blocks.append(prose(
            "block:navigation-start",
            "To follow the code from the outside in, start at: %s."
            % ", ".join(e["path"] for e in entries[:5])))
    return blocks


def class_views_page(index):
    """The inheritance forest, for the files where class detail was extracted."""
    if not index.get("coverage", {}).get("detail_requested"):
        return [prose("block:class-views-none",
                      "The scan did not extract class detail, so no inheritance is "
                      "described here. Rerun the scanner with --detail.")]

    rows = []
    for record in sorted(index.get("files", ()), key=lambda r: r["path"]):
        for cls in record.get("classes", ()):
            for base in cls.get("bases", ()):
                # An unresolved base is a name, not a link. Saying where it came from
                # would be a guess, so the row says plainly that it is unresolved.
                target = ("%s (%s)" % (base["name"], base["resolved"])
                          if base.get("resolved") else
                          "%s (not resolved to a file in this repository)" % base["name"])
                rows.append((cls["name"], target, cite(record["path"], cls["line"])))
    if not rows:
        return [prose("block:class-views-none",
                      "Class detail was extracted, but no class in this repository "
                      "inherits from another.")]
    return [
        prose("block:class-views-intro",
              "Every class that names a base. A base links to a file only when the "
              "import resolved and that file really defines a class by that name."),
        table("block:class-views", ("Class", "Inherits", "Defined at"), rows),
    ]


def limitations_page(index, fragments, claims):
    coverage = index.get("coverage", {})
    rows = [
        ("files scanned", str(coverage.get("files_scanned", 0))),
        ("parsed exactly", str(coverage.get("files_exact", 0))),
        ("regex-approximated", str(coverage.get("files_approximate", 0))),
        ("not examined (no parser)", str(coverage.get("files_unscanned", 0))),
        ("imports naming nothing in this repository",
         str(coverage.get("unresolved_imports", 0))),
        ("symlinks skipped (target outside the root)",
         str(coverage.get("skipped_symlinks", 0))),
        ("modules described", str(len(fragments))),
        ("claims verified", str(sum(1 for c in claims if c.get("status") == "verified"))),
    ]
    blocks = [
        prose("block:limitations-intro",
              "What was covered, and what this document does not know."),
        table("block:coverage", ("Measure", "Count"), rows),
    ]

    # The Ruff annotation surfaces here or nowhere. Stated with its caveat attached,
    # because an unused binding is not evidence that a dependency is unnecessary.
    usage = coverage.get("import_usage")
    if usage and usage.get("tool_available"):
        blocks.append(prose(
            "block:limitations-import-usage",
            "Ruff reports %d imported binding(s) that are never read, out of %d "
            "annotated. That is not evidence the dependency is unnecessary: re-export, "
            "side effect, registration and dynamic discovery all look the same from "
            "here. %d diagnostic(s) could not be tied to an import statement."
            % (usage.get("unused_bindings", 0), usage.get("annotated", 0),
               usage.get("unmatched", 0))))
    elif usage:
        blocks.append(prose(
            "block:limitations-import-usage",
            "Import usage was not checked -- Ruff was unavailable or disabled -- so no "
            "claim is made about whether an imported name is ever read."))

    unresolved = [c for c in claims if c.get("status") in LIMITATION_STATUSES]
    if unresolved:
        blocks.append(prose(
            "block:limitations-unresolved-intro",
            "These statements could not be established from the source. They are listed "
            "rather than written into the document as facts."))
        blocks.append(table(
            "block:limitations-unresolved", ("Claim", "Kind", "Status"),
            [(c.get("id", ""), c.get("kind", ""), c.get("status", ""))
             for c in sorted(unresolved, key=lambda c: c.get("id", ""))]))

    diagnostics = index.get("diagnostics", ())
    if diagnostics:
        blocks.append(table(
            "block:limitations-diagnostics", ("Code", "Path", "Note"),
            [(d.get("code", ""), d.get("path") or "-", d.get("message", ""))
             for d in diagnostics]))
    return blocks


BUILDERS = {
    "overview": lambda index, fragments, claims, by_id: overview_page(index, fragments, by_id),
    "entry-points": lambda index, fragments, claims, by_id: entry_points_page(index),
    "architecture": lambda index, fragments, claims, by_id: architecture_page(index, by_id),
    "dependencies": lambda index, fragments, claims, by_id: dependencies_page(index),
    "modules": lambda index, fragments, claims, by_id: modules_page(index, fragments, by_id),
    "flows": lambda index, fragments, claims, by_id: flows_page(index, by_id),
    "navigation": lambda index, fragments, claims, by_id: navigation_page(index),
    "class-views": lambda index, fragments, claims, by_id: class_views_page(index),
    "limitations": lambda index, fragments, claims, by_id: limitations_page(
        index, fragments, claims),
}


def build(index, fragments, claims, preset):
    by_id = {c.get("id"): c for c in claims}
    pages = []
    for order, (page_id, title, mandatory) in enumerate(PRESETS[preset], 1):
        blocks = BUILDERS[page_id](index, fragments, claims, by_id)
        pages.append({"id": page_id, "title": title, "order": order,
                      "mandatory": mandatory, "blocks": blocks})

    # Every page but the last points at the next one, so navigation exists in the model
    # rather than being invented by each renderer.
    for page, following in zip(pages, pages[1:]):
        page["blocks"].append({"id": "block:%s-next" % page["id"], "type": "ref",
                               "target": following["id"]})

    return {
        "format_version": FORMAT_VERSION,
        "generator_version": GENERATOR_VERSION,
        "preset": preset,
        "source_revision": (index.get("source") or {}).get("revision"),
        "source_dirty": (index.get("source") or {}).get("dirty"),
        "pages": pages,
        "claims": sorted(claims, key=lambda c: c.get("id", "")),
        "coverage": index.get("coverage", {}),
    }


def validate(doc):
    """Structural problems that would produce a broken or dishonest page."""
    problems = []
    by_id = {c.get("id"): c for c in doc["claims"]}
    page_ids, block_ids = set(), set()

    for page in doc["pages"]:
        if page["id"] in page_ids:
            problems.append("duplicate page id %r" % page["id"])
        page_ids.add(page["id"])
        if not page["blocks"]:
            problems.append("page %r has no blocks" % page["id"])

    for page in doc["pages"]:
        for block in page["blocks"]:
            if block["id"] in block_ids:
                problems.append("duplicate block id %r" % block["id"])
            block_ids.add(block["id"])
            if block["type"] == "ref" and block["target"] not in page_ids:
                problems.append("block %r references page %r, which does not exist"
                                % (block["id"], block["target"]))
            for claim_id in block.get("claim_refs", ()):
                claim = by_id.get(claim_id)
                if claim is None:
                    problems.append("block %r cites claim %r, which is not in the model"
                                    % (block["id"], claim_id))
                elif claim.get("status") not in PROSE_STATUSES:
                    # The boundary this script exists to hold.
                    problems.append("block %r cites claim %r, which is %s and may not "
                                    "appear in prose"
                                    % (block["id"], claim_id, claim.get("status")))

    for page_id, _, mandatory in PRESETS[doc["preset"]]:
        if mandatory and page_id not in page_ids:
            problems.append("preset %r requires page %r" % (doc["preset"], page_id))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", default="structure.json", help="path to structure.json")
    parser.add_argument("--claims", required=True, help="verified claims, JSONL")
    parser.add_argument("--fragments", required=True, help="verified fragments, JSONL")
    parser.add_argument("--preset", default="onboarding", choices=sorted(PRESETS))
    parser.add_argument("--out", default=".docs-build/doc.json")
    args = parser.parse_args()

    if not os.path.isfile(args.index):
        sys.stderr.write("FAIL  no such index: %s\n" % args.index)
        return 2
    try:
        with open(args.index, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("FAIL  cannot read %s: %s\n" % (args.index, exc))
        return 2
    if index.get("schema_version") not in SUPPORTED_SCHEMA:
        sys.stderr.write("FAIL  %s declares schema_version %r; this script supports %s\n"
                         % (args.index, index.get("schema_version"), sorted(SUPPORTED_SCHEMA)))
        return 2

    claims, error = load_rows(args.claims, "claims")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2
    fragments, error = load_rows(args.fragments, "fragments")
    if error:
        sys.stderr.write("FAIL  %s\n" % error)
        return 2

    rejected = [c["id"] for c in claims if c.get("status") == "rejected"]
    if rejected:
        # Building anything from a set containing a claim the source contradicts would
        # mean deciding, silently, which parts of it to keep.
        sys.stderr.write("FAIL  %d rejected claim(s) in the input: %s\n"
                         % (len(rejected), ", ".join(sorted(rejected)[:5])))
        sys.stderr.write("      revise or drop them, then rerun verify_doc.py\n")
        return 2

    doc = build(index, fragments, claims, args.preset)
    problems = validate(doc)
    if problems:
        for problem in problems:
            sys.stderr.write("  %s\n" % problem)
        sys.stderr.write("FAIL  %d problem(s); nothing written\n" % len(problems))
        return 1

    directory = os.path.dirname(os.path.abspath(args.out))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)

    print("wrote %s: %d page(s), %d block(s), %d claim(s)"
          % (args.out, len(doc["pages"]),
             sum(len(p["blocks"]) for p in doc["pages"]), len(doc["claims"])))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
