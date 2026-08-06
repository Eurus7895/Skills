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

> Adding a plugin means adding a row here **and** an entry in
> [`.github/plugin/marketplace.json`](.github/plugin/marketplace.json).

## Install

### Copilot CLI (recommended)

Register this repository as a plugin marketplace, then install the plugins you want:

```bash
copilot plugin marketplace add Eurus7895/Skills
copilot plugin install <plugin-name>@eurus-skills
```

Useful companions:

```bash
copilot plugin marketplace list          # marketplaces you have registered
copilot plugin marketplace browse eurus-skills
copilot plugin list                      # plugins you have installed
copilot plugin update <plugin-name>
copilot plugin uninstall <plugin-name>
```

Inside an interactive Copilot session, the same commands work as `/plugin install <plugin-name>@eurus-skills`.

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

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md). If you are an AI agent, read [`AGENTS.md`](AGENTS.md) first.

## Safety

Skills are injected directly into an agent's context and are **not verified by GitHub**. Treat every line of a
`SKILL.md` and every bundled script as executable instruction, and review anything you install from any
marketplace — including this one.
