# Document — what the pages will say

The fourth component. Presets are in [`presets.md`](presets.md), diagram rules in
[`diagram-policy.md`](diagram-policy.md), and the manual preset in [`manual.md`](manual.md).

```bash
python3 scripts/pipeline.py document --docs docs
```

Validates each of the three analyses that exists and skips the ones that do not, naming them; then builds the
class graph and its diagrams, draws any traced flow as a sequence, and builds `doc.json`.

- **Read** every `B0xx`, `F0xx`, `O0xx` and `G0xx` finding, and the page and block counts.
- **Decide** nothing about markup — `doc.json` carries none. Fix what a finding points at: a file absent here
  is a visibly thinner document, which is the honest outcome; a file present but wrong is not.

**Past a density threshold the class diagram becomes several** — read the run's output for how many. A
`view-spec.json` may choose detail, layers and emphasis; it may **not** add a class, drop one, change what
connects to what, or set its own scope. See [`diagram-policy.md`](diagram-policy.md).

The preset is chosen from what the build directory holds: `outside-in` once any of the three analyses exists,
`onboarding` otherwise, and `--preset` overrides. `outside-in` opens on what the repository is rather than on
its dependency graph. **`--preset manual`** requires `.docs-build/manual-analysis.json` and renders the
sections you composed from its answers — never the template questions themselves, which are the prompt and
not the document. Read [the manual guide](manual.md) before
building it. `handbook` preserves its existing authored-page workflow. All presets are described in
[`presets.md`](presets.md).
