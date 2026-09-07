#!/usr/bin/env python3
"""Resolve a pipeline script by name, wherever its component keeps it.

The scripts under `shared/scripts/` are grouped by the component that owns them --
`survey/`, `analyze/`, `check/`, `document/`, `publish/`. Tests care which script they are
running and not which directory it sits in, so they ask for it by name:

    from component_scripts import script
    subprocess.run([sys.executable, script("scan_repo.py"), ...])

A name that matches nothing raises rather than returning a path that does not exist, so a
script renamed out from under a test fails as a missing script instead of as a mysterious
non-zero exit with no output.
"""

import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")
COMPONENTS = ("survey", "analyze", "check", "document", "publish")


def script(name):
    """The absolute path of `name`, searched in the components and then beside them."""
    for component in COMPONENTS:
        candidate = os.path.join(SCRIPTS, component, name)
        if os.path.isfile(candidate):
            return candidate
    candidate = os.path.join(SCRIPTS, name)
    if os.path.isfile(candidate):
        return candidate
    raise FileNotFoundError("no script named %r under shared/scripts/" % name)


def component_paths():
    """Every directory holding pipeline scripts, for a test that imports one as a module.

    A test that reaches inside a script -- for its constants, or to call a function
    directly -- needs the component directories on `sys.path`, and needs all of them:
    `quality_docs` imports across two components itself.
    """
    return [os.path.join(SCRIPTS, component) for component in COMPONENTS] + [SCRIPTS]


def component_of(name):
    """Which component owns `name` -- the directory, or None for a top-level script."""
    for component in COMPONENTS:
        if os.path.isfile(os.path.join(SCRIPTS, component, name)):
            return component
    return None
