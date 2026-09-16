#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/build_dir.py
# Regenerate: python3 tools/materialize.py
"""Create the intermediate directory, and make it ignore itself.

`.docs-build/` holds the run's working artefacts -- the index, the claims, the analyses,
the answer draft. None of it is meant to be committed: it is regenerated from the source
tree, it goes stale the moment the tree moves, and a diff full of it hides the change the
commit is actually about.

Leaving that to the person running the skill means every repository it touches has to
learn the same lesson once, by seeing the directory in `git status` and going to add a
line. So the directory ignores itself the moment it is made.

**The rule is `*`, which covers the `.gitignore` too.** The usual `*` plus `!.gitignore`
exists to keep the ignore file itself committable, and here that would be backwards: the
whole directory is disposable, so nothing in it should reach a commit, the marker least
of all. Git sees an empty spot where the build directory is.

**An existing `.gitignore` is never overwritten.** Someone who edited it wanted something
this default does not do, and replacing that on the next run would be the pipeline
arguing with them once per invocation.

This is only for intermediates. The rendered document is a deliverable and is meant to be
committed, so nothing here touches the output directory.

Standard library only.
"""

import os

IGNORE_NAME = ".gitignore"
IGNORE_BODY = """\
# Written by the documentation pipeline when it created this directory.
#
# Everything here is intermediate: it is rebuilt from the source tree on the next run and
# goes stale as soon as that tree moves. Regenerate it rather than committing it.
#
# `*` deliberately covers this file too -- the whole directory is disposable, so nothing
# in it should reach a commit. Delete this file if you would rather track the build.
*
"""


def ensure(directory):
    """Create `directory` if it is absent and give it a self-ignoring `.gitignore`.

    Returns True when this call created the directory. Safe to call on every run: the
    marker is written once and an edited one is left alone.
    """
    created = not os.path.isdir(directory)
    if created:
        os.makedirs(directory)
    marker = os.path.join(directory, IGNORE_NAME)
    if not os.path.exists(marker):
        try:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write(IGNORE_BODY)
        except OSError:
            # A read-only or otherwise unwritable build directory is the caller's
            # problem to report when it fails to write the artefact it came here for.
            # Failing the run over a convenience marker would be the tail wagging the dog.
            pass
    return created


def ensure_parent(path):
    """The same, for a file whose directory may not exist yet."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        ensure(directory)
    return directory
