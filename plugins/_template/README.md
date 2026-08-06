# _template

**This is scaffolding, not an installable plugin.** It is excluded from
[`marketplace.json`](../../.github/plugin/marketplace.json) on purpose.

## How to use it

1. Copy the whole folder:

   ```bash
   cp -r plugins/_template plugins/my-plugin-name
   ```

2. Edit `plugins/my-plugin-name/.github/plugin/plugin.json` — set `name` to `my-plugin-name` (it must match the
   folder), write a real `description`, and list your skills in `skills`.
3. Rename `skills/example-skill/` to your skill's name and rewrite its `SKILL.md`. Delete
   `references/example.md` if you do not need it.
4. Rewrite this README using the template below.
5. Register the plugin in [`.github/plugin/marketplace.json`](../../.github/plugin/marketplace.json) and add a
   row to the catalog in the [root README](../../README.md).

See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the full standard.

---

## README template for your plugin

```markdown
# my-plugin-name

One or two sentences on the job this plugin helps with.

## Install

    copilot plugin marketplace add Eurus7895/Skills
    copilot plugin install my-plugin-name@CopilotBox

## Skills

- **`skill-one`** — what it does, and when it fires.
- **`skill-two`** — what it does, and when it fires.

## Notes

Anything a user should know before running it: side effects, required tools, assumptions.
```
