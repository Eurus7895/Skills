---
applyTo: "**"
priority: P4
description: What this repository is and how it is laid out — a plugin marketplace with no application, the source-versus-generated split, which files are authored and which are produced by tooling, and the checks that gate a commit.
---

# Repository Layout — Project (P4)

## What this repository is

A **plugin marketplace**. It ships plugins; each plugin bundles one or more Agent Skills.

There is no application here — no build, no test suite, no runtime, no dependencies to install. Do not look
for a `package.json` to run, and do not add a toolchain unless explicitly asked. The deliverable is always
Markdown and JSON, plus standard-library Python.

Agent Skills are an open standard. Nothing here may use syntax specific to one vendor.

## Layout

```
AGENTS.md                     entry point for agents working in this repo
CONTRIBUTING.md               the normative authoring standard
.github/
  copilot-instructions.md     repository-wide instructions
  instructions/               these files — path-scoped instructions
  plugin/marketplace.json     the marketplace manifest
shared/                       SOURCE for content used by more than one plugin — never installed
tools/
  materialize.py              copies shared/ into the plugins that declare it
  validate.py                 structural checks — run before every commit
plugins/
  _template/                  scaffolding; not a real plugin
  <plugin>/
    .github/plugin/plugin.json
    shared.manifest           which shared/ paths this plugin pulls, and where
    skills/<skill>/SKILL.md
fixtures/                     deliberately broken projects for evaluating the plugins
```

## Source versus generated

`shared/` is **source only** and is never installed. `tools/materialize.py` copies its contents into each
plugin that lists them in `shared.manifest`, and **those copies are committed** — a plugin installs standalone
and cannot reach back into the repository.

- Files carrying a `GENERATED` banner are produced by tooling. Never hand-edit one.
- To change generated content: edit the file under `shared/`, run `python3 tools/materialize.py`, and commit
  both the source and the regenerated copies.
- `tools/validate.py` fails on drift between a source and its copies.

## Where a rule belongs

| Kind of rule | Home |
| ------------ | ---- |
| Applies to agents working **in this repository** | `.github/instructions/` and `AGENTS.md` |
| Explains *why* an authoring rule exists | `CONTRIBUTING.md` |
| Must ship **inside an installed plugin** | The `SKILL.md` body, via `shared/` + materialize |

The third row is the one that catches people. Nothing in this repository's root reaches a user's machine, so a
rule that must hold at runtime cannot live in `AGENTS.md`, `CONTRIBUTING.md`, or these instruction files.

## Before committing

```bash
python3 tools/validate.py        # manifests, frontmatter, links, catalog, drift
python3 tools/materialize.py     # regenerate copies after editing shared/
```

`validate.py` must exit 0. It is the gate, and it subsumes the manual checks.
