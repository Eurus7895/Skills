# Analyze — what you need in front of you

The second component, and **what the model's budget buys — the only part of the run that carries
understanding.** Row shapes, kinds and statuses are in [`schemas.md`](schemas.md); packets, partitions and
the append discipline are in [`context-policy.md`](context-policy.md).

**Checkpoint P2 closes this component**, and `check` will not run until it is decided.

```bash
python3 scripts/pipeline.py analyze
```

Derives every claim the index already supports and writes one context packet per unit to
`.docs-build/packets/`. **What follows is what the model's budget buys, and the only part of the run that
carries understanding.**

- **Read** each packet: source, symbols, edges both ways with the line that proves each, neighbours' public
  interfaces, and the manifest of what was left out.
- **Decide** what the module is *for*, what it owns, how it fails, and why a boundary is where it is. Those go
  in `.docs-build/module-analysis.jsonl`, one row per module.

**Do not hand-write a `defines`, `imports`, `inherits` or `contains` claim.** This component already derived
every one of them, so writing them out spends budget copying a table and buys a chance of copying it wrong.
**A `calls` claim is the one kind still worth writing by hand**: it needs a call site you actually read.
Append those to `.docs-build/claims.jsonl` — and note that re-running `analyze` rewrites that file, which is
why it refuses to when hand-written claims are in it.

A packet that says `partitioned: true` has parts to fetch, and `query_graph.py` is the one script you call
yourself:

```bash
python3 scripts/analyze/query_graph.py --index .docs-build/structure.json --root . --part '<id>'
```

The row shape, the six `kind`s and the four `status`es are in
[`schemas.md`](schemas.md). Two rules decide whether a statement counts. **It must name
something that is in the module it describes** — a sentence true of every module in the repository is about
none of them. And `unknown` is a real answer: where the repository never says why, say that instead of
inventing a reason.

**Say what the module works with, not only what it is called.** Naming one thing in the file is the floor the
anchoring rule enforces, and a sentence that stops there — *"main handles the duties assigned to this
module"* — is true, cites a resolving line, passes every check, and tells a reader nothing. A reading relates
the module to its collaborators, so it names them: what it builds, what it hands over, what it raises. `A016`
measures this, and a whole analysis written that way fails the run.

**Answer all four of `responsibility`, `state`, `interface` and `failure` for every module.** They are the four
headings a module page renders, so a kind you skip is a heading a reader meets empty — and the quality gate
counts them: two of four is a module read, four of four is one answered, and a run of one-line modules is
`partial` no matter how cleanly its claims verify. This is also where `unknown` earns its place. A module with
no recorded failure behaviour gets a `failure` statement saying the repository does not record one; silence
there reads to the gate as a question nobody asked, because that is usually what it is.

Each scope also produces **one fragment line** in `.docs-build/fragments.jsonl`, naming the derived claims it
stands on — flat JSON, one object per line, no array:

```json
{"fragment_id": "fragment:src/api.py", "source": "src/api.py", "role": "Exposes the HTTP boundary and delegates to application services.", "claim_ids": ["claim:imports:src/api.py:src/service.py"], "status": "candidate", "index_hash": "sha256:…"}
```

Three rules hold for every row you write, whatever else you skip:

- **If the packet says `partitioned: true`, fetch every part** with `--part '<id>'` before describing the
  module. A part you did not read is a part you are describing blind.
- **Copy `index_hash` verbatim** from the survey into every row, so a row left in `.docs-build/` by an earlier
  run cannot pass for one written a minute ago.
- **You do the appending.** Create both files empty, then one scope, one append. If the analysis is fanned
  out, each parallel task returns its lines *to you*: two writers on one JSONL file interleave into corrupt
  lines, and it surfaces much later as a parse error.

Why each of those matters, how to read a packet and its omission manifest, and the other query modes are in
[`context-policy.md`](context-policy.md).

**Pause here — P2.** Every page downstream is built on these roles, and no later stage can tell a wrong role
from a right one.

**Put a bounded list in front of them, not one line per module.** Fifty lines of your own prose handed over for
confirmation is the review load that produces a habitual yes, and a checkpoint answered out of habit is worse
than none: it leaves a record saying somebody looked. The refusal `check` gives computes the list for you —
every module that recorded an `unknown`, every one with fewer than the four kinds answered, and a sample of the
settled ones. Show that, and ask about those.

**A decision needs at least five words saying what you went on.** `--note "ok"` is refused. Deciding unattended
is still a decision you may record — say that, and say what you accepted, because the closing report carries
the note verbatim as the evidence that this question was answered.
