# Skills

A collection of [Agent Skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) for
GitHub Copilot, grouped into installable **plugins**.

Agent Skills are an open standard, so everything here also works in Claude Code and any other skills-compatible
agent. Nothing in this repo uses Copilot-only syntax.

## Plugin catalog

| Plugin | Skills | What it's for |
| ------ | ------ | ------------- |
| [`testing`](plugins/testing/) | `write-tests`, `review-tests`, `debug-failing-test` | Write, audit, and debug automated tests in whatever framework the repo already uses |
| [`code-review`](plugins/code-review/) | `review-code`, `setup-review-rules` | Review code against Google's Standard of Code Review, and generate a repo's agent/review rules files |
| [`large-context`](plugins/large-context/) | `synthesize-corpus`, `document-codebase`, `audit-codebase` | Answer counting, ranking, and full-coverage questions over corpora larger than the context window, with coverage verified rather than assumed |

> Adding a plugin means adding a row here **and** an entry in
> [`.github/plugin/marketplace.json`](.github/plugin/marketplace.json).

## Install

### Copilot CLI (recommended)

Register this repository as a plugin marketplace, then install the plugins you want:

```bash
copilot plugin marketplace add Eurus7895/Skills
copilot plugin install <plugin-name>@CopilotBox
```

The marketplace registers under the name in its manifest — **`CopilotBox`** — not under the repository
name. `add` takes `Eurus7895/Skills`; everything afterwards takes `CopilotBox`. The name is
case-sensitive.

Useful companions:

```bash
copilot plugin marketplace list          # marketplaces you have registered
copilot plugin marketplace browse CopilotBox   # what this marketplace offers
copilot plugin marketplace update CopilotBox   # re-read the catalog (alias: refresh)
copilot plugin marketplace remove CopilotBox   # --force also uninstalls its plugins
copilot plugin list                      # plugins you have installed
copilot plugin update <plugin-name>
copilot plugin uninstall <plugin-name>
```

Inside an interactive Copilot session, the same commands work as `/plugin install <plugin-name>@CopilotBox`.

### Installing from a branch, or from a local checkout

`add` reads the repository's **default branch**. To install work that has not been merged yet, name the ref
with `#` — `@` is not the separator, and `owner/repo@ref` is parsed as a hostname:

```bash
copilot plugin marketplace add Eurus7895/Skills#some-branch
```

`add` also accepts a **directory** — the folder containing `.github/plugin/marketplace.json`, not the file
itself. From a checkout of this repo:

```bash
copilot plugin marketplace add .
```

### Troubleshooting

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| `Available plugins: none` | The catalog is cached, or the default branch has no plugins yet | `copilot plugin marketplace update CopilotBox`; if the plugins are on an unmerged branch, re-add with `#branch` |
| `Marketplace "CopilotBox" already registered` | `add` will not overwrite a registration | `update` to refresh it, or `remove` then `add` |
| `File not found: marketplace.json, ...` listing doubled paths | A path to the manifest file was passed | Pass the directory that contains `.github/plugin/`, e.g. `.` |
| `Repository not found` on a ref | `@` used instead of `#` | `owner/repo#ref` |
| `Marketplace "eurus-skills" ...` | A registration from before this marketplace was renamed | `copilot plugin marketplace remove eurus-skills --force`, then `add` again |

### VS Code

Open the Extensions view and search `@agentPlugins`, or run **Chat: Plugins** from the Command Palette.

### Manual — a single skill, no CLI

Every skill is a self-contained folder. Copy the one you want out of `plugins/<plugin>/skills/<skill>/` into
any directory Copilot scans:

| Scope | Directories |
| ----- | ----------- |
| One repository | `.github/skills/`, `.claude/skills/`, or `.agents/skills/` |
| All your projects | `~/.copilot/skills/` or `~/.agents/skills/` |

## Where skills work

Copilot coding agent, Copilot code review, Copilot CLI, the GitHub Copilot app, and agent mode in VS Code,
Visual Studio, and JetBrains IDEs.

## Layout

```
.
├── AGENTS.md                          # start here if you are an AI agent
├── CONTRIBUTING.md                    # the authoring standard
├── docs/
│   └── GENERAL.md                     # conventions every skill inlines
├── .github/
│   ├── copilot-instructions.md
│   ├── instructions/                  # path-scoped rules, applied automatically by glob
│   └── plugin/
│       └── marketplace.json           # the marketplace manifest
├── shared/                            # SOURCE for content used by more than one plugin
│   ├── references/
│   └── scripts/
├── tools/
│   ├── materialize.py                 # copies shared/ into the plugins that declare it
│   └── validate.py                    # structural checks — run before every commit
└── plugins/
    ├── _template/                     # copy this to start a new plugin
    ├── testing/
    └── code-review/
        ├── .github/plugin/plugin.json
        ├── shared.manifest            # which shared/ paths this plugin pulls, and where
        ├── README.md
        └── skills/<skill-name>/
            ├── SKILL.md
            ├── references/            # generated from shared/, plus skill-specific docs
            └── scripts/
```

Folders prefixed with `_` are scaffolding, not real plugins. They are deliberately absent from
`marketplace.json` and cannot be installed.

`shared/` is **source only** — it is never installed. `tools/materialize.py` copies its contents into each
plugin that lists them in `shared.manifest`, and those copies are committed, because a plugin installs
standalone and cannot reach back into the repository. Never hand-edit a generated file; edit `shared/` and
re-run the script.

## Checks

```bash
python3 tools/validate.py        # manifests, frontmatter, links, catalog, drift
python3 tools/materialize.py     # regenerate copies after editing shared/
```

Both run in CI on every pull request, against Python 3.9 and 3.13 — the floor proves the bundled scripts do
not depend on newer syntax, since they run on a stranger's machine with no install step. Run them locally
anyway; a red pull request is a slower way to learn the same thing.

## Fixtures

[`fixtures/`](fixtures/) holds deliberately broken sample projects for demonstrating and evaluating the
plugins — buggy code with a stated contract, a wrong test against correct code, a green-but-worthless suite,
and planted vulnerabilities. Each scenario asks whether the agent **finds** the defect or **accommodates** it.

Open one scenario folder at a time; `fixtures/EXPECTED.md` is the answer key and must stay out of the session
being demoed. See [`fixtures/README.md`](fixtures/README.md).

Note: those scenarios carry their own `pyproject.toml`, so running `detect_stack.py` against the repository
root now reports Python/pytest. That is the fixtures, not this repo — pass a target path to scope it.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md). If you are an AI agent, read [`AGENTS.md`](AGENTS.md) first.

## Safety

Skills are injected directly into an agent's context and are **not verified by GitHub**. Treat every line of a
`SKILL.md` and every bundled script as executable instruction, and review anything you install from any
marketplace — including this one.
