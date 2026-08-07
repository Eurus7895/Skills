---
name: audit-codebase
description: Sweep an entire repository for one stated concern — a vulnerability class, a missing guard, a
  convention, an unfinished migration — and report every occurrence with file, line, and a verbatim quote whose
  presence in the code is machine-verified. Use when the target is the whole codebase rather than a change, and
  the answer must be complete: "audit this repo for X", "find every place that Y", "where are we still doing
  Z", "is this migration finished", "sweep the codebase for", "which files are missing W". For reviewing a
  diff, pull request, branch, or uncommitted work, use `review-code` instead — that is a change review, this is
  a whole-repository sweep. For describing what a repository does rather than finding occurrences in it, use
  `document-codebase`. Do not use on a single file, or on a repo small enough to read directly.
---

# Sweep a whole repository for one concern

Narrow with code, examine every in-scope file, collect findings into one table, verify each citation against
the real file, then rank. The deliverable is a severity-ordered report in which every finding quotes code that
was proven to exist, and a coverage section stating exactly which files were examined.

## When to use this skill

- The target is **the repository as it stands**, not a change to it.
- The answer must be **exhaustive** — "every place", "all files missing", "is it fully migrated".
- Missing an occurrence is a real failure: security, compliance, a migration that must not be half-done.
- The repo is too large to read in full.

## When not to use this skill

- **A diff, pull request, branch, or working tree** is the target. Use `review-code` — it reviews changes
  against a review standard, which is a different job with a different output.
- **Describing the system** rather than finding occurrences. Use `document-codebase`.
- **A single file or function.** Read it and answer.
- **A repo small enough to read directly.** Read it; this pipeline's overhead buys nothing.

## Hard rules

1. **Every finding carries `file`, `line`, and a verbatim `quote` copied from the source.** A finding that
   cannot be quoted does not ship — it is an impression, not an observation.
2. **Verify citations before writing the report.** Run `scripts/verify_findings.py`. A quote that is not in the
   code is a fabricated citation, not a near miss: drop the finding or correct it. Never report an unverified
   one.
3. **Coverage before severity.** State which files were examined and which were not. "No findings" over a
   partial sweep is false, and it is the most damaging thing this skill can output.
4. **Ask the open question before the closed filter.** Grep the codebase for how the concern is actually
   spelled before narrowing on one spelling. A pattern that matches nothing looks identical to a codebase that
   is clean.
5. **Per-file tasks report observations, not rankings.** Severity comparison happens after assembly, when every
   file's findings sit in one table. A file examined alone cannot know it holds the worst case.
6. **Report; do not patch.** Confirm before editing anything.

## Steps

### 1. State the concern as a checkable property

Write down what a finding *is* before looking for anything. Vague framing produces vague findings.

```
concern:   passwords hashed with a fast algorithm
a finding: a call to md5/sha1/sha256 whose input is a password or credential
not a finding: md5 used for cache keys or file checksums
```

The "not a finding" line matters as much as the other two — it is what keeps the sweep from drowning in noise.

### 2. Scan the repository

**Run it; you do not need to read it.**

```bash
python3 scripts/scan_repo.py --root . --out structure.json --summary --top 20
```

Read the digest. It gives file and line totals, languages, exactly-parsed counts, skipped symlinks, and the
fan-in ranking. Note the total file count — it is the denominator for coverage.

### 3. Discover how the concern is spelled, then narrow

Open question first:

```bash
grep -rioE "md5|sha1|sha256|bcrypt|scrypt|argon2|pbkdf2" --include="*.py" . | \
  awk -F: '{print tolower($NF)}' | sort | uniq -c | sort -rn | head
```

Now you know the vocabulary actually present. Narrow on it, and record the in-scope list:

```bash
grep -rlE "md5|sha1|sha256" --include="*.py" . | sort > scope.txt
wc -l scope.txt
```

State how many files the filter removed and on what criterion. If the concern cannot be grepped — "error
handling is missing" has no marker — skip narrowing and take the fan-in ranking's top files plus every entry
point instead, and say that the sweep is ranked rather than exhaustive.

### 4. Examine every in-scope file

Dispatch one task per file, in parallel batches:

```
File: src/auth.py

Concern: passwords hashed with a fast algorithm.
A finding is a call to md5/sha1/sha256 whose input is a password or credential.
md5 for cache keys or checksums is NOT a finding.

Return one JSON object per line, no prose, no markdown fence:
  file:     "src/auth.py"
  line:     integer, the line the finding is on
  severity: one of [high, medium, low]
  category: short kebab-case slug, e.g. weak-hash
  claim:    one sentence stating the defect
  quote:    the line, copied EXACTLY as it appears -- do not reformat or paraphrase

If this file has nothing, return exactly one object with severity "none",
category "none", claim "no findings", and line and quote null.

Do not rank against other files. Do not suggest fixes. Report only what is here.

<file contents>
```

The mandatory "none" row is what makes coverage provable in the next step: a file that returned nothing at all
is indistinguishable from a task that silently failed.

### 5. Assemble and check coverage

**Run it; you do not need to read it.**

```bash
python3 scripts/assemble.py \
  --input findings.jsonl \
  --schema "file:str, line:int?, severity:enum(high|medium|low|none), category:str, claim:str, quote:str?" \
  --unit-field file \
  --units "$(wc -l < scope.txt)" \
  --unit-list scope.txt \
  --rows-per-unit many \
  --out findings.csv
```

`--rows-per-unit many` is required here: one file can hold several findings. Coverage is proven by
`--unit-list` — every file in `scope.txt` must appear, and the "none" rows are what make the clean ones appear.

Resolve every FAILURE before continuing. Judge each WARNING and say what you concluded.

### 6. Verify every citation

**Run it; you do not need to read it.**

```bash
python3 -c "
import json
rows = [json.loads(l) for l in open('findings.jsonl') if l.strip()]
real = [r for r in rows if r.get('severity') != 'none']
open('cited.jsonl','w').write('\n'.join(json.dumps(r) for r in real))
print('%d finding(s) to verify' % len(real))
"
python3 scripts/verify_findings.py --input cited.jsonl --root .
```

It reads each cited file and confirms the quote is really at that line. Exit code 1 means at least one finding
cites code that does not exist.

Drop or correct every unverified finding. Report how many were dropped — a fabricated citation is worth
stating, because it tells the reader how much to trust the rest.

### 7. Rank and report

Only now compare across files. Count from the table, do not eyeball it:

```bash
python3 -c "
import csv, collections
rows = [r for r in csv.DictReader(open('findings.csv')) if r['severity'] != 'none']
print(collections.Counter(r['severity'] for r in rows))
print(collections.Counter(r['category'] for r in rows).most_common())
"
```

## Output format

Produce exactly this, with no commentary around it:

```
## Audit: <concern>

<one or two sentences: what was found, at what scale>

| Severity | Count |
| -------- | ----- |
| high     |     4 |
| medium   |    11 |
| low      |     3 |

### high

1. **weak-hash** — `src/auth.py:5`
   Password compared using an unsalted MD5 digest.
   `return hashlib.md5(password.encode()).hexdigest() == stored`

2. **weak-hash** — `src/legacy/session.py:88`
   Session token derived with SHA-1.
   `token = hashlib.sha1(seed).hexdigest()`

### medium

...

## Coverage

- files in repo:        412
- narrowed to scope:    38 (contain one of md5|sha1|sha256, case-insensitive)
- files examined:       38 of 38
- files with findings:  12
- files clean:          26
- citations verified:   18 of 20; 2 dropped as unverifiable
- validator warnings:   none
- not examined:         none

## Method

- concern: passwords hashed with a fast algorithm; md5 for checksums excluded
- vocabulary confirmed by grep before narrowing
- severities compared only after all findings were in one table
```

When the sweep was ranked rather than exhaustive (step 3), say so in **Coverage** and name the ranking
criterion. Never present a ranked sweep as complete.

## Bundled resources

| Path | Load when |
| ---- | --------- |
| `scripts/scan_repo.py` | Step 2, always — before reading any source file. Run it; you do not need to read it. |
| `scripts/assemble.py` | Step 5, always. Run it; you do not need to read it. |
| `scripts/verify_findings.py` | Step 6, always, before any finding is reported. Run it; you do not need to read it. |

## Side effects

Writes `structure.json`, `scope.txt`, `findings.jsonl`, `cited.jsonl`, and `findings.csv` into the working
directory. Reads the working tree only; paths resolving outside the scanned root are refused. No network
access, no package installation — every script is standard library only.

## Conventions

- Reference bundled files by paths relative to this skill folder.
- Report what was done and what was skipped; never claim success for something that was not verified. A partial
  result reported honestly is more useful than a complete result that is not true.
- Report failures with the actual output, not a paraphrase.
- Confirm before anything destructive or hard to reverse, and before anything outward-facing. Approval for one
  action does not carry to the next.
- Look at the target before overwriting or deleting it.
- Assume no network access and no package installation.
- Produce exactly the output format defined above, with no commentary wrapped around it.
