# Rendering, and writing into somebody else's project

`doc.json` contains no markup. **Never write RST, MyST or Sphinx directives by hand** — the
renderer owns headings, tables, references, escaping and the toctree. Hand-written
directives are how a build starts failing on markup nobody remembers adding.

## Formats

`--format` chooses the markup: `rst` (the default) or `myst`. The same `doc.json` renders
to both, page for page and reference for reference; only the emitter differs.

**MyST needs the target project to enable `myst_parser`.** Markdown pages in a project that
has not are files Sphinx will not read, and the build fails for a reason that has nothing to
do with the pages. That is refused before anything is written, unless `--assume-parser` says
the project configures extensions somewhere this cannot see.

**`sphinxcontrib-plantuml` is a different kind of dependency and is optional.** Without a
parser a page is never read at all; without the diagram extension every page still builds
and one picture is missing, and the `.puml` beside it is the artifact either way. A project
without it gets every page, a warning naming what to enable, and a build check that accepts
the `uml` directive without drawing it.

## The six outcomes of `--check`

`--check` runs `sphinx-build -W` when Sphinx is installed, falls back to docutils, and
reports `skipped` when neither is present. The outcomes are not interchangeable:

| Outcome | Means | Next |
| --- | --- | --- |
| `passed` | builds, every reference resolves | nothing |
| `unwired` | builds; some pages are in no toctree yet | wire them in, or say the document is not yet part of the project's index |
| `invalid_markup` | a page does not parse | a defect — report the output |
| `broken_reference` | parses, but points at something absent | fix the target or the reference |
| `runner_failure` | the builder could not run | the check learned nothing about the markup |
| `skipped` | no builder installed | **not a pass** — say so |

`unwired` and `skipped` do not fail the run. Neither is a pass either, and reporting one as
a pass is the failure this table exists to prevent.

## Two flags that touch what the author wrote

Both are off by default, for that reason.

- **`--wire-toctree`** adds the generated pages to an index that already exists. It is
  idempotent, keeps every entry and every line of prose that was there, and **refuses** an
  index with no toctree, with more than one, or that it cannot parse — leaving the file
  untouched and naming the pages to add by hand. Without the flag the pages are written and
  the run prints what is missing; the build check then reports `unwired`, and wiring is what
  turns that into `passed`.
- **`--assume-parser`** writes MyST into a project whose `conf.py` does not visibly enable
  `myst_parser`. `conf.py` is read as text, never imported — running a stranger's
  configuration to find out what it configures is not a check, it is execution.

## `--write-conf`, and what it does not do

Generated pages are not a document until something can build them, and a project that has
never used Sphinx has no `conf.py` to build them with. Without one, `sphinx-build docs/` on
a freshly rendered tree fails on configuration, not on anything the pages say.

`--write-conf` writes one — **once, only when asked, and only when the directory has none.**
It never overwrites and never edits. That is the same rule as reading a `conf.py` as text
rather than importing it, for the same reason: a configuration is somebody's, it can contain
anything, and a generator that rewrites it destroys work no rerun can restore. A second run
against a directory that has one prints `kept the existing conf.py` and moves on.

`--project` and `--author` fill in the two fields nothing can derive.

**A required extension and an optional one are written differently, and the difference is not
cosmetic.** `myst_parser` goes straight into `extensions`, because MyST pages are unreadable
without it. `sphinxcontrib.plantuml` must not: naming an extension there that is not installed
makes Sphinx raise `ExtensionError` while importing it and produce *no page at all*, which is
the opposite of optional. So the generated file imports it inside a `try`, appends it when it
is there, and otherwise registers `uml` as a directive that draws nothing — because leaving it
unregistered turns every `.. uml::` into an unknown directive and `-W` fails the build for the
other reason. Either way every page builds and the only difference is whether the picture
appears.

Without the flag nothing is written, and a run into a directory with no `conf.py` says so:
the pages are on disk and cannot yet be built, which is not visible from the files alone.

## The `handbook` preset

For a repository that already has a documentation tree in the usual
`getting_started/ architecture/ usage/ development/ appendix/` shape. It fills the four
pages a dependency graph can answer for and writes none of the others: an installation guide
or a changelog is not derivable from code, and a generated stub would replace what someone
wrote. The renderer lists each page it did not generate, and keeps an existing `index.rst`.

For those authored pages the work is an **update, not a generation**: read what is there,
check it against `claims.verified.jsonl`, and change only what the evidence contradicts or
completes — same citations, same status boundary. Anything you cannot check against the
graph, leave as the author wrote it, and report which pages you touched and which you did
not.
