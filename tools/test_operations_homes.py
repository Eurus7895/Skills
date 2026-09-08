#!/usr/bin/env python3
"""Every operation kind a preset can be handed must have a page that renders it.

The two-way `covers` check in `build_document_model` guards statement kinds: a preset
that declares a kind and gives it no page is caught, and a page that renders a kind no
preset declares is caught. Procedures have no such check, and the gap was not
hypothetical -- the `manual` preset split the operations analysis across four pages and
dropped `run` between them. A `run` procedure written by hand in step 4, quoting a
command out of the README, rendered nowhere and reported nothing.

That is worse than an empty page. An empty page says the analysis recorded nothing; a
dropped kind says nothing at all, and the reader concludes the repository has no way to
run it.

Standard library only. Exit code 0 when every preset that renders procedures renders all
of them, 1 otherwise.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from component_scripts import component_paths  # noqa: E402

sys.path[:0] = component_paths()

import build_document_model as model  # noqa: E402
import validate_operations  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


# Every home names kinds the schema defines. A typo here would silently render nothing.
for home, kinds in sorted(model.PROCEDURE_HOMES.items()):
    for kind in kinds:
        check(kind in validate_operations.PROCEDURE_KINDS,
              "PROCEDURE_HOMES[%r] names %r, which is not an operation kind"
              % (home, kind))

# Each preset that renders any procedure at all must render every kind. A preset is free
# to have no operations pages -- `onboarding` mostly does not -- but one that has some
# and not others loses whatever the analysis recorded for the rest.
for preset, rows in sorted(model.PRESETS.items()):
    builders = [row[3] for row in rows if row[3]]
    homes = [b for b in builders if b in model.PROCEDURE_HOMES]
    if not homes:
        continue
    covered = set()
    for home in homes:
        covered.update(model.PROCEDURE_HOMES[home])
    missing = sorted(set(validate_operations.PROCEDURE_KINDS) - covered)
    check(not missing,
          "preset %r renders procedures but has no page for: %s"
          % (preset, ", ".join(missing)))

    # The same kind on two pages is the other half of the contract: a reader meeting the
    # test commands twice cannot tell which page is the one to trust.
    for kind in validate_operations.PROCEDURE_KINDS:
        seen = [h for h in homes if kind in model.PROCEDURE_HOMES[h]]
        check(len(seen) <= 1,
              "preset %r renders %r on more than one page: %s"
              % (preset, kind, ", ".join(sorted(seen))))

# Every home in the table is reachable through the builder registry, so a page cannot be
# declared and then not exist.
for home in sorted(model.PROCEDURE_HOMES):
    check(home in model.BUILDERS,
          "PROCEDURE_HOMES names %r, which is not a builder" % home)

# The specific regression: `manual` must render `run` somewhere.
manual_builders = [row[3] for row in model.PRESETS["manual"] if row[3]]
check(any("run" in model.PROCEDURE_HOMES.get(b, ()) for b in manual_builders),
      "the manual preset renders no page for the `run` procedure kind")

if failures:
    for line in failures:
        sys.stderr.write("FAIL  %s\n" % line)
    sys.exit(1)
print("OK  operation kinds have exactly one home in every preset that renders them")
