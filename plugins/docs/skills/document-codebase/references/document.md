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

**`manual` is the default**, and `--preset` picks any other. It renders the sections you composed from the
template answers — never the template questions themselves, which are the prompt and not the document. Read
[the manual guide](manual.md) before building it.

**On the first run there is no answer artifact, so `document` writes the draft and stops**, exit `1`: a
verdict, not breakage. It writes unanswered slots and a `facts` inventory from whichever validated inputs
exist; it writes no answer prose. It tells you to read the source, answer the slots and compose the pages,
and does not overwrite a draft that is already there.
Rerun `document` once it is answered.

The graph-driven presets are one flag away and are still the right answer for an architecture report rather
than a manual: `outside-in` opens on what the repository is rather than on its dependency graph,
`onboarding` is the file-by-file tour, `architecture` the dense shape, and `handbook` fits an existing
documentation tree and preserves its authored pages. All of them are described in
[`presets.md`](presets.md).
