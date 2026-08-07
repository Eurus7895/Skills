---
applyTo: "**/plugin.json,**/marketplace.json,**/shared.manifest"
priority: P3
description: Rules for plugin.json, marketplace.json, and shared.manifest — manifest location, name and description parity between plugin and catalog, the four different description fields and their audiences, and version bumping.
---

# Manifests — Domain Standard (P3)

## Where manifests live

| File | Path |
| ---- | ---- |
| Marketplace | `.github/plugin/marketplace.json` |
| Plugin | `plugins/<name>/.github/plugin/plugin.json` |

`.github/plugin/` is a valid manifest location — the resolver checks `.plugin/`, `plugin.json`,
`.github/plugin/`, and `.claude-plugin/`. Do not "fix" this by moving manifests to the plugin root.

## Parity — enforced by the validator

- `plugin.json` `name` **must equal** its folder name.
- `marketplace.json` `plugins[].description` and `version` must be **byte-identical** to the plugin's own
  `plugin.json`. Changing one means changing both.
- `marketplace.json` `plugins[].source` must be `plugins/<name>`.
- Every skill folder must appear in the plugin's `skills[]` array, and every `skills[]` path must resolve.
- Every plugin needs a row in the root `README.md` catalog.
- Folders prefixed with `_` are scaffolding. They stay out of `marketplace.json` and cannot be installed.

## The four `description` fields

They have different audiences. Only the first affects agent behaviour.

| Where | Audience | Write it for |
| ----- | -------- | ------------ |
| `SKILL.md` frontmatter | **The model**, always in context | Matching — trigger phrases, disambiguation |
| `plugin.json` | Human, after installing | What they got |
| `marketplace.json` → `plugins[]` | Human, browsing before install | Why install it |
| `marketplace.json` → `metadata` | Human, browsing the collection | What the collection is |

Never write a `SKILL.md` description as marketing copy. It is a matcher.

## Marketplace name

The marketplace registers under the `name` in its manifest, **not** the repository name, and it is
case-sensitive. Renaming it means updating every `plugin install <plugin>@<marketplace>` reference in every
Markdown file — `tools/validate.py` fails the build if any drift.

## Versions

- Semantic versioning. Bump the plugin's `version` in **both** `plugin.json` and `marketplace.json` whenever
  its skills change behaviour.
- A documentation-only fix does not need a bump. A changed procedure, output contract, or trigger does.

## `shared.manifest`

Newline-delimited `src -> dest`, where `src` is relative to `shared/` and `dest` is relative to the plugin.

- Destinations are **per skill** — `skills/<skill>/references/…`, not the plugin root — because a `SKILL.md`
  resolves bundled paths relative to its own folder.
- The file is source, not a build artifact. `.gitignore` has `*.manifest`; the negation
  `!plugins/*/shared.manifest` is load-bearing. Do not remove it.
- After editing `shared/`, run `python3 tools/materialize.py`. Never hand-edit a generated copy.
