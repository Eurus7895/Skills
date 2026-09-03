#!/usr/bin/env python3
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

`--analysis` brings in `module-analysis.jsonl`, and it is what stops the document reading
like an inventory. A claim can only ever say that one file imports another; every page
built from claims alone therefore says structural things, and structural things read as
generic however well they are phrased. The statements carry what a module is *for*, what
it owns, how it fails and why a boundary is where it is, and they have their own status
boundary, parallel to the one above:

    declared             the repository says so -- an ADR, a design note, a docstring
    observed             read out of the code, cited to the lines it was read from
    inferred             a reading; rendered with the hedge attached, never as a fact
    unknown              the repository never says; named in Limitations, never in prose

Without `--analysis` this writes the same document it always did, minus nothing. That is
deliberate: a run that did no per-module reading should produce a visibly thinner
document rather than a document that hides how little was read.

Exit codes: 0 written, 1 the model is not valid, 2 input/schema error, 3 internal error.

Standard library only. Reads its inputs; writes only --out.
"""

import argparse
import json
import os
import sys

FORMAT_VERSION = 2
GENERATOR_VERSION = "0.2.0-dev"
SUPPORTED_SCHEMA = {2, 3}
SUPPORTED_MANIFEST_SCHEMA = {3}
SUPPORTED_ANALYSIS_VERSION = {1}

PROSE_STATUSES = ("verified", "supported_inference")
LIMITATION_STATUSES = ("candidate", "unsupported", "needs_context")

# The statement vocabulary. Separate from the claim one on purpose: a claim is checked
# against the source and can be contradicted by it, a statement is a reading and cannot.
STATEMENT_PROSE_STATUSES = ("declared", "observed", "inferred")
STATEMENT_LIMITATION_STATUSES = ("unknown",)

# How a statement is introduced, so a reader can tell a quotation from a deduction
# without reading the schema. `inferred` gets the hedge in the sentence itself, because
# the citation is the weakest place to put it -- a reader skims past a parenthesis.
BASIS = {
    "declared": "The repository states this",
    "observed": "Read at",
    "inferred": "Inferred from",
}

# Which statement kinds each kind of page is responsible for. This is the `covers`
# contract: a kind named nowhere is a kind whose statements the document would silently
# drop, which is exactly the failure this pass exists to make loud.
#
# Each kind has exactly one home. Rendering `interaction` on both the architecture page
# and the flows page would read as two findings where there is one, and would make the
# coverage denominator below meaningless.
COVERS = {
    "modules": ("responsibility", "state", "interface", "failure"),
    "architecture": ("interaction", "rationale"),
}

KIND_TITLES = {
    "responsibility": "What it is responsible for",
    "state": "What it owns",
    "interface": "How it is used",
    "failure": "How it fails",
    "interaction": "How it works with the rest of the tree",
    "rationale": "Why the boundary is here",
}

# A preset fixes the skeleton: which pages exist, in what order, and which of them may
# not be dropped. It says nothing about what is true -- that comes from the claims.
#
# Each row is (page_id, title, mandatory, builder). `builder` names the function that
# fills the page from the graph, or is None for a page this pipeline cannot fill.
#
# A page id is also its path under the output directory, so an id may contain "/" and
# the layout of an existing documentation tree can be matched exactly.
PRESETS = {
    "onboarding": [
        ("overview", "Overview", True, "overview"),
        ("entry-points", "Entry points", True, "entry-points"),
        ("architecture", "Architecture", True, "architecture"),
        ("flows", "Important flows", True, "flows"),
        ("modules", "Module reference", True, "modules"),
        ("navigation", "Finding your way around", True, "navigation"),
        ("limitations", "Coverage and limitations", True, "limitations"),
    ],
    # No module reference here by design: this preset is for a reader who already knows
    # the domain and wants the shape, not the inventory.
    "architecture": [
        ("overview", "Architecture overview", True, "overview"),
        ("architecture", "Components and boundaries", True, "architecture"),
        ("dependencies", "Dependency graph", True, "dependencies"),
        ("class-views", "Classes and inheritance", True, "class-views"),
        ("flows", "Cross-component flows", True, "flows"),
        ("limitations", "Coverage and limitations", True, "limitations"),
    ],
    # A handbook laid out the way a delivered manual usually is. Most of it is not
    # derivable from a dependency graph -- an installation guide, a changelog, a
    # glossary are things a person knows -- so this pipeline fills the four pages that
    # are, lists the rest, and writes none of them. Those stay the author's, and the
    # skill updates them against verified claims one at a time.
    "handbook": [
        ("getting_started/introduction", "Introduction", True, None),
        ("getting_started/installation_integrators", "Installation", True, None),
        ("getting_started/quick_start_integration", "Quick start", True, None),
        ("architecture/key_modules", "Key modules", True, "architecture"),
        ("architecture/class_diagrams", "Class diagrams", True, "class-views"),
        ("architecture/data_flow", "Data flow", True, "flows"),
        ("usage/invoking_main_class", "Invoking the main class", True, None),
        ("usage/configuration_parameters", "Configuration parameters", True, None),
        ("usage/operational_modes_details", "Operational modes", True, None),
        ("usage/handling_output_results", "Handling output", True, None),
        ("usage/error_handling_exceptions", "Errors and exceptions", True, None),
        ("development/local_setup_for_dev", "Local setup", True, None),
        ("development/testing", "Testing", True, None),
        ("development/packaging_release", "Packaging and release", True, None),
        ("development/contribution_guide", "Contributing", True, None),
        ("development/module_reference", "Module reference", True, "modules"),
        ("development/ci_cd_workflow", "CI and CD", True, None),
        ("changelog", "Changelog", False, None),
        ("appendix/glossary", "Glossary", False, None),
        ("appendix/faq", "FAQ", False, None),
        ("appendix/troubleshooting", "Troubleshooting", False, None),
        ("appendix/references", "References", False, None),
        ("appendix/compliance", "Compliance", False, None),
        ("appendix/output_structure", "Output structure", False, None),
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


def prose(block_id, text, claim_refs=(), analysis_refs=()):
    return {"id": block_id, "type": "prose", "text": text,
            "claim_refs": sorted(claim_refs), "analysis_refs": sorted(analysis_refs)}


def subheading(block_id, text):
    return {"id": block_id, "type": "subheading", "text": text,
            "claim_refs": [], "analysis_refs": []}


class Analysis(object):
    """The per-module reading, indexed by the two questions the pages ask of it.

    Holds nothing that is not in the file. The point of the class is that a page asks
    for a kind and gets back every statement of that kind in module order, so two pages
    cannot disagree about which statements exist.
    """

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.by_id = {}
        self._by_kind = {}
        for row in self.rows:
            path = row.get("path", "")
            for statement in row.get("statements", ()):
                statement = dict(statement, path=path)
                self.by_id[statement.get("id")] = statement
                self._by_kind.setdefault(statement.get("kind"), []).append(statement)

    def __bool__(self):
        return bool(self.rows)

    __nonzero__ = __bool__                                    # Python 2 name, harmless

    def kinds_present(self):
        """Kinds that have at least one statement a page could render or list."""
        return {kind for kind, rows in self._by_kind.items() if rows}

    def of_kind(self, kind, statuses):
        out = [s for s in self._by_kind.get(kind, ())
               if s.get("status") in statuses]
        return sorted(out, key=lambda s: (s.get("path", ""), s.get("id", "")))

    def modules(self):
        return {row.get("path", "") for row in self.rows}


def sentence(statement):
    """One statement as a sentence a reader can weigh, with its basis attached.

    The hedge on an `inferred` statement goes at the front rather than in the citation.
    A reader who skims the parenthesis has still read the word "Inferred"; a reader who
    skims the front of the sentence has not read anything.
    """
    text = str(statement.get("text", "")).strip()
    evidence = (statement.get("evidence") or [{}])[0]
    path, start = evidence.get("path"), evidence.get("line_start")
    where = cite(path, start) if path and isinstance(start, int) else statement.get("path", "")
    basis = BASIS.get(statement.get("status"), "From")
    if statement.get("status") == "inferred":
        return "Inferred: %s (%s %s)" % (text, basis.lower(), where)
    return "%s (%s %s)" % (text, basis.lower(), where)


def statement_blocks(page_id, analysis, kinds):
    """The statements this page is responsible for, grouped by kind then by module.

    Grouped by kind and not by module because the kinds answer different questions, and
    a reader looking for how something fails should not have to read every module's
    responsibility to find it.
    """
    blocks = []
    for kind in kinds:
        statements = analysis.of_kind(kind, STATEMENT_PROSE_STATUSES)
        if not statements:
            continue
        blocks.append(subheading("block:%s-%s" % (page_id, kind), KIND_TITLES[kind]))
        by_module = {}
        for statement in statements:
            by_module.setdefault(statement.get("path", ""), []).append(statement)
        for path in sorted(by_module):
            group = by_module[path]
            blocks.append(prose(
                "block:%s-%s-%s" % (page_id, kind, path.replace("/", "-")),
                "%s -- %s" % (path, " ".join(sentence(s) for s in group)),
                analysis_refs=[s.get("id") for s in group]))
    return blocks


def table(block_id, columns, rows, claim_refs=()):
    return {"id": block_id, "type": "table", "columns": list(columns),
            "rows": [list(r) for r in rows], "claim_refs": sorted(claim_refs)}


def diagram(block_id, src, alt):
    return {"id": block_id, "type": "plantuml", "src": src, "alt": alt}


def cite(path, line):
    return "%s:%d" % (path, line)


def diagram_blocks(diagrams, page_id):
    """A PlantUML directive block per generated Diagram as Code source."""
    if not diagrams:
        return []
    blocks = []
    for name, alt in diagrams.get(page_id, ()):
        blocks.append(diagram("block:%s-diagram-%s" % (page_id, os.path.splitext(name)[0]),
                              "_diagrams/%s" % name, alt))
    return blocks


def find_diagrams(directory, page_ids=()):
    """Which generated PlantUML views exist, mapped to documentation pages."""
    if not directory or not os.path.isdir(directory):
        return {}
    manifest_path = os.path.join(directory, "diagram-manifest.json")
    if not os.path.isfile(manifest_path):
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return {}
    if manifest.get("schema_version") not in SUPPORTED_MANIFEST_SCHEMA:
        # An unreadable manifest means no figure, never a guessed one.
        return {}

    overview, details = [], []
    for entry in manifest.get("views", ()):
        source = entry.get("file")
        if not source or not source.endswith(".puml") \
                or not os.path.isfile(os.path.join(directory, source)):
            continue
        scope = entry.get("scope") or {"kind": "repository"}
        layers = " and ".join(entry.get("layers", ())) or "no"
        # The view's own classes, not the neighbours it draws to show its boundary.
        own = entry.get("scope_nodes")
        count = len(own if own is not None else entry.get("nodes", ()))
        if scope.get("kind") == "repository":
            overview.append((source, "Class diagram of the whole repository: %d class(es) "
                                  "grouped by package and module, showing %s "
                                  "relationships" % (count, layers)))
        else:
            name = str(scope.get("id", "")).split(":", 1)[-1]
            neighbours = len(entry.get("nodes", ())) - count
            details.append((source, "Class diagram of %s: %d class(es)%s, showing %s "
                                 "relationships"
                            % (name or "one scope", count,
                               " plus %d neighbour(s) outside it" % neighbours
                               if neighbours > 0 else "", layers)))
    if not overview and not details:
        return {}
    # The overview belongs on every page that talks about structure. The detail views go
    # wherever classes are discussed, and land on the architecture page when the preset
    # has no page for classes -- a rendered view that no page references is a file the
    # reader has no way to reach.
    for candidate in ("class-views", "architecture/class_diagrams", "architecture"):
        if candidate in page_ids:
            home = candidate
            break
    else:
        home = "architecture"
    on_structure = [p for p in ("architecture", "class-views",
                                "architecture/key_modules", "architecture/class_diagrams")
                    if p in page_ids] or ["architecture", "class-views"]
    placed = {page: list(overview) for page in on_structure}
    placed[home] = placed.get(home, []) + details
    return placed


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
            ("Module", "Depended on by", "Basis", "Role"),
            [(f["source"], str(fan_in.get(f["source"], 0)),
              "verified" if f["status"] == "verified" else "inferred",
              f.get("role", ""))
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


def architecture_page(index, claims_by_id, analysis):
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

    # The table above says which modules reach into which. What that reaching is for,
    # and why the boundary sits where it does, is not in the graph and has to come from
    # somebody who read the code.
    blocks.extend(statement_blocks("architecture", analysis, COVERS["architecture"]))
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


def modules_page(index, fragments, claims_by_id, analysis):
    fan_in = index.get("fan_in", {})
    rows, refs = [], set()
    for fragment in sorted(fragments, key=lambda f: f.get("source", "")):
        if fragment.get("status") not in PROSE_STATUSES:
            continue
        # A role resting only on a responsibility claim is a reading of the code, not a
        # structural fact, and it must not sit in the same column as one that is. The
        # status is shown rather than the two being run together.
        rows.append((fragment["source"], str(fan_in.get(fragment["source"], 0)),
                     "verified" if fragment["status"] == "verified" else "inferred",
                     fragment.get("role", "")))
        refs.update(c for c in fragment.get("claim_ids", ())
                    if claims_by_id.get(c, {}).get("status") in PROSE_STATUSES)
    if not rows:
        return [prose("block:modules-none",
                      "No module description survived verification. Nothing is stated "
                      "here rather than stating something unchecked.")]
    blocks = [
        prose("block:modules-intro",
              "One row per module whose description survived verification. `verified` "
              "means every claim behind the role was checked against the graph or the "
              "source; `inferred` means the role rests on a reading of the code that no "
              "pass could confirm."),
        table("block:modules", ("Path", "Imported by", "Basis", "Role"), rows, refs),
    ]
    # The table is the index. The sections below are the part of this document a reader
    # could not have worked out from the file tree.
    blocks.extend(statement_blocks("modules", analysis, COVERS["modules"]))
    return blocks


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


def limitations_page(index, fragments, claims, analysis):
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

    # Questions the run put to the repository and the repository did not answer. Listing
    # them is the difference between a document that was not asked and one that asked and
    # got nothing, and only the second tells a reader where to go looking.
    unanswered = []
    for kind in sorted(KIND_TITLES):
        unanswered.extend(analysis.of_kind(kind, STATEMENT_LIMITATION_STATUSES))
    if unanswered:
        blocks.append(prose(
            "block:limitations-unknown-intro",
            "These were looked for and not found. The repository does not record them "
            "anywhere this run could read, so they are named here rather than guessed at "
            "in the pages above."))
        blocks.append(table(
            "block:limitations-unknown", ("Module", "Question", "What is missing"),
            [(s.get("path", ""), KIND_TITLES.get(s.get("kind"), s.get("kind", "")),
              str(s.get("text", "")).strip())
             for s in sorted(unanswered, key=lambda s: (s.get("path", ""),
                                                        s.get("id", "")))]))

    diagnostics = index.get("diagnostics", ())
    if diagnostics:
        blocks.append(table(
            "block:limitations-diagnostics", ("Code", "Path", "Note"),
            [(d.get("code", ""), d.get("path") or "-", d.get("message", ""))
             for d in diagnostics]))
    return blocks


BUILDERS = {
    "overview": lambda index, frags, claims, by_id, an: overview_page(index, frags, by_id),
    "entry-points": lambda index, frags, claims, by_id, an: entry_points_page(index),
    "architecture": lambda index, frags, claims, by_id, an: architecture_page(
        index, by_id, an),
    "dependencies": lambda index, frags, claims, by_id, an: dependencies_page(index),
    "modules": lambda index, frags, claims, by_id, an: modules_page(
        index, frags, by_id, an),
    "flows": lambda index, frags, claims, by_id, an: flows_page(index, by_id),
    "navigation": lambda index, frags, claims, by_id, an: navigation_page(index),
    "class-views": lambda index, frags, claims, by_id, an: class_views_page(index),
    "limitations": lambda index, frags, claims, by_id, an: limitations_page(
        index, frags, claims, an),
}


def section_coverage(preset, analysis, fragments):
    """One denominator per section, not one for the whole tree.

    A single "82% covered" figure hides which of the questions went unanswered, and the
    questions are not interchangeable: a document that knows what every module is for and
    nothing about how any of them fails is not 90% of a document.
    """
    scope = sorted({f.get("source", "") for f in fragments} | analysis.modules())
    out = {}
    for page_id, _, _, builder in PRESETS[preset]:
        kinds = COVERS.get(builder or "", ())
        if not kinds:
            continue
        out[page_id] = {
            kind: {
                "modules_stated": len({s.get("path") for s
                                       in analysis.of_kind(kind, STATEMENT_PROSE_STATUSES)}),
                "modules_unknown": len({s.get("path") for s
                                        in analysis.of_kind(
                                            kind, STATEMENT_LIMITATION_STATUSES)}),
                "modules_in_scope": len(scope),
            }
            for kind in kinds}
    return out


def build(index, fragments, claims, preset, diagrams=None, analysis=None):
    by_id = {c.get("id"): c for c in claims}
    analysis = analysis if analysis is not None else Analysis()
    pages, authored = [], []
    for order, (page_id, title, mandatory, builder) in enumerate(PRESETS[preset], 1):
        if builder is None:
            # A page this pipeline has no evidence for. It is named, so the skill knows
            # to update it and the report can say it was not generated, and it is not
            # written -- a stub would replace whatever the author already has there.
            authored.append({"id": page_id, "title": title, "order": order,
                             "mandatory": mandatory})
            continue
        blocks = BUILDERS[builder](index, fragments, claims, by_id, analysis)
        blocks.extend(diagram_blocks(diagrams, page_id))
        pages.append({"id": page_id, "title": title, "order": order,
                      "mandatory": mandatory, "blocks": blocks,
                      # What this page undertook to say, and which statements it used
                      # saying it. The pair is what makes the check below two-way.
                      "covers": list(COVERS.get(builder, ())),
                      "analysis_ids": sorted({ref for block in blocks
                                              for ref in block.get("analysis_refs", ())})})

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
        # Named, not written. The renderer leaves them alone and the skill updates them
        # from verified claims; a generated stub would overwrite the author's work.
        "authored_pages": authored,
        "claims": sorted(claims, key=lambda c: c.get("id", "")),
        "statements": sorted(analysis.by_id.values(),
                             key=lambda s: (s.get("path", ""), s.get("id", ""))),
        "coverage": index.get("coverage", {}),
        "coverage_by_section": section_coverage(preset, analysis, fragments),
    }


def validate(doc):
    """Structural problems that would produce a broken or dishonest page."""
    problems = []
    by_id = {c.get("id"): c for c in doc["claims"]}
    statements_by_id = {s.get("id"): s for s in doc.get("statements", ())}
    page_ids, block_ids = set(), set()

    for page in doc["pages"]:
        if page["id"] in page_ids:
            problems.append("duplicate page id %r" % page["id"])
        page_ids.add(page["id"])
        if not page["blocks"]:
            problems.append("page %r has no blocks" % page["id"])
        elif all(block["type"] in ("ref", "subheading") for block in page["blocks"]):
            # A heading and a link to the next page. It renders, it validates, and it
            # tells the reader nothing -- which is worse than being absent, because the
            # toctree promises it holds something.
            problems.append("page %r has nothing to say: every block is a heading or a "
                            "link" % page["id"])

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
            for statement_id in block.get("analysis_refs", ()):
                statement = statements_by_id.get(statement_id)
                if statement is None:
                    problems.append("block %r cites statement %r, which is not in the "
                                    "model" % (block["id"], statement_id))
                elif statement.get("status") not in STATEMENT_PROSE_STATUSES:
                    # The same boundary, for the other vocabulary. `unknown` on a page is
                    # a sentence asserting the thing the run recorded as not knowable.
                    problems.append("block %r cites statement %r, which is %s and may "
                                    "not appear in prose"
                                    % (block["id"], statement_id, statement.get("status")))

    # Two-way, and this direction is the one that was missing: a statement kind the
    # analysis produced but no page in the preset claims to cover is a reading that was
    # paid for and thrown away.
    covered = {kind for page in doc["pages"] for kind in page.get("covers", ())}
    dropped = {}
    for statement in doc.get("statements", ()):
        kind = statement.get("kind")
        if kind not in covered and statement.get("status") in STATEMENT_PROSE_STATUSES:
            dropped[kind] = dropped.get(kind, 0) + 1
    for kind in sorted(dropped):
        problems.append("no page in preset %r covers statement kind %r; %d statement(s) "
                        "would be dropped" % (doc["preset"], kind, dropped[kind]))

    authored_ids = {p["id"] for p in doc.get("authored_pages", ())}
    for page_id, _, mandatory, builder in PRESETS[doc["preset"]]:
        if builder is None:
            if mandatory and page_id not in authored_ids:
                problems.append("preset %r requires page %r" % (doc["preset"], page_id))
            continue
        if mandatory and page_id not in page_ids:
            problems.append("preset %r requires page %r" % (doc["preset"], page_id))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", default="structure.json", help="path to structure.json")
    parser.add_argument("--claims", required=True, help="verified claims, JSONL")
    parser.add_argument("--fragments", required=True, help="verified fragments, JSONL")
    parser.add_argument("--analysis", metavar="PATH",
                        help="module-analysis.jsonl; without it the pages carry only "
                             "what the graph can prove, which is an inventory")
    parser.add_argument("--preset", default="onboarding", choices=sorted(PRESETS))
    parser.add_argument("--diagrams", metavar="DIR",
                        help="rendered diagram directory; pages reference what is there "
                             "and nothing more")
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

    analysis = Analysis()
    if args.analysis:
        rows, error = load_rows(args.analysis, "analysis")
        if error:
            sys.stderr.write("FAIL  %s\n" % error)
            return 2
        unsupported = sorted({row.get("analysis_version") for row in rows
                              if row.get("analysis_version") not in SUPPORTED_ANALYSIS_VERSION},
                             key=str)
        if unsupported:
            sys.stderr.write("FAIL  %s declares analysis_version %s; this script supports "
                             "%s\n" % (args.analysis, ", ".join(repr(v) for v in unsupported),
                                       sorted(SUPPORTED_ANALYSIS_VERSION)))
            return 2
        analysis = Analysis(rows)
        uncovered = analysis.kinds_present() - set(KIND_TITLES)
        if uncovered:
            sys.stderr.write("FAIL  %s holds statement kind(s) this script does not know: "
                             "%s\n" % (args.analysis, ", ".join(sorted(uncovered))))
            return 2

    rejected = [c["id"] for c in claims if c.get("status") == "rejected"]
    if rejected:
        # Building anything from a set containing a claim the source contradicts would
        # mean deciding, silently, which parts of it to keep.
        sys.stderr.write("FAIL  %d rejected claim(s) in the input: %s\n"
                         % (len(rejected), ", ".join(sorted(rejected)[:5])))
        sys.stderr.write("      revise or drop them, then rerun verify_doc.py\n")
        return 2

    diagrams = find_diagrams(args.diagrams,
                             [page_id for page_id, _, _, _ in PRESETS[args.preset]])
    if args.diagrams and not diagrams:
        # Asked for, not found: say so rather than producing a document that quietly
        # has no picture in it.
        sys.stderr.write("WARN  %s holds no generated PlantUML diagram; the pages will "
                         "have no diagram\n" % args.diagrams)
    doc = build(index, fragments, claims, args.preset, diagrams, analysis)
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

    print("wrote %s: %d page(s), %d block(s), %d claim(s), %d statement(s)"
          % (args.out, len(doc["pages"]),
             sum(len(p["blocks"]) for p in doc["pages"]), len(doc["claims"]),
             len(doc["statements"])))
    if not args.analysis:
        print("no --analysis: the pages carry what the graph proves and nothing that was "
              "read, which is why they read like an inventory")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
