# The three analyses — what the repository is, how it runs, how it is operated

**No command.** These three files are yours to write, between `check` and `document`, and they are what
checkpoint P3 asks about. They are read by the `outside-in` preset and by `manual`, whose initializer adds
their eligible ids to the draft's `facts` inventory so the model can inspect and cite them while writing answers.
They do not write or complete an answer. Every schema and finding code is in
[`schemas.md`](schemas.md).

**`architecture-analysis.json`** — components, the layers they sit in, what crosses between them, and which
outside systems the repository talks to. **The easy way to produce this file is to read the directory listing
and rename it** — `src/api/` becomes "API layer", `src/core/` becomes "Core" — and the result has components,
layers and a shape while telling a reader nothing `ls` would not. Detector B, in the quality gate that ends
[`publish.md`](publish.md), measures that and fails the run for it. The work is deciding where the boundaries actually are: which modules serve one purpose
whatever folder they sit in, which folder holds two unrelated things, and why each boundary is where it is.
Three rules do most of it: **a module belongs to one component**, **a relationship cites a line** whatever its
status because it is the part that says what breaks what, and **a rationale of `unknown` is a real answer**.

**`flow-analysis.json`** — **a step is a call `check` verified at its call site, and nothing else.** An import
edge is the weaker claim that two files reference each other, not that the request passes through here. Steps
must join up on the same *entity*, because the order is the entire claim. **Expect `absent`**: a call through
`self.service.record(...)` is not name-bound by an import, so it cannot be read at its call site. Write
`absent` with a reason rather than something flow-shaped; an empty list saying nothing fails the gate.

**`operations-analysis.json`** — install, build, test, configure, run, deploy, release and observe. **Quote
commands from the file**: a `command` or a requirement `value` must appear character for character in the
lines it cites.

Both of the last two are best effort, and a repository that yields neither says so.

**Pause here — P3.** Detector B can tell you the components are the directory tree; nobody but the user can
tell you they are the wrong components. Show the boundaries and the rationale for each, name what was
traced and what came back `absent`, and ask.
