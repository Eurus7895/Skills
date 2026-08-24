# Context policy

This skill cannot choose the host model, so the limits below are conservative defaults for a 200k-token
window rather than a measurement of anything. They exist to make the partitioning decision reproducible.

## Budgets

| Task | Soft target | Hard ceiling |
| --- | ---: | ---: |
| Scope analysis | 32k | 48k |
| Architecture synthesis | 24k | 40k |
| Page generation | 12k | 20k |
| Targeted revision | 8k | 16k |

`query_graph.py` applies the scope-analysis pair and exposes both as `--soft-limit` and `--hard-limit`.
Lowering only the ceiling pulls the target down with it rather than erroring.

Token counts are **characters divided by four**. That is an estimate and is labelled as one in every packet
(`token_estimate_is_an_estimate`). Do not report it as a cost.

## What always goes in the packet

- the scope's own source;
- its symbols and, where detail exists, its classes;
- every import edge in and out, with the line that proves it;
- edges that cross a directory boundary, called out separately;
- each neighbour's public interface — names and kinds, never bodies;
- findings from the previous attempt, when retrying.

## What gets summarised first

Neighbour bodies, then private implementations. Both are already reduced to interfaces before any limit is
reached, so in practice the ceiling is only met by one very large file.

## Over the ceiling

The packet is **partitioned**, never trimmed. `query_graph.py` splits the file along its own top-level
definitions, returns `partitioned: true` with a list of parts, and sends no source at all until a part is
named with `--part`. The parts tile the file with no gap, and each part's manifest lists the others.

A file with no top-level definitions to split on — one enormous function, a generated data table — is
refused with exit `2` rather than truncated. Truncation is the failure mode this whole design exists to
prevent: a model given half a file describes it confidently and has no way to know what it missed.

## Retrying

A retry sends the **same scope** plus exactly what the finding asked for:

```bash
python3 scripts/query_graph.py --index .docs-build/structure.json \
    --packet src/api.py --include src/service.py --findings .docs-build/findings.jsonl
```

Revise only the affected fragment. Two attempts, then stop — and a finding that repeats (`V020`) means stop
immediately, because the loop is no longer making progress and a third attempt will produce the same answer
more expensively.

## Scope budget

Model calls scale with the number of scopes dispatched, not with repository size. The default is the top ~25
modules by fan-in plus every entry point; everything else gets one line in a grouped list. Raising that is a
deliberate choice with a cost, and the cutoff used belongs in the document so a reader knows what was and was
not examined closely.
