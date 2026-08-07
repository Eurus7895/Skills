# Copilot instructions

This repository is a **GitHub Copilot plugin marketplace**. It does not contain an application — it contains
plugins, and each plugin bundles Agent Skills.

Read [`AGENTS.md`](../AGENTS.md) before doing anything in this repo. It describes the layout, the rules, and
what "done" means here.

Read [`CONTRIBUTING.md`](../CONTRIBUTING.md) before writing or editing a skill or a plugin. It is the normative
authoring standard.

Path-scoped rules live in [`instructions/`](instructions/) and are applied automatically by `applyTo` glob —
safety and conduct everywhere, plus rules specific to `SKILL.md` files, manifests, Python, and fixtures. Where
an instruction file disagrees with `CONTRIBUTING.md`, `CONTRIBUTING.md` wins and the instruction file is the
bug.
