#!/usr/bin/env python3
"""Copy shared/ sources into the plugins that declare them.

A plugin installs standalone, so anything a SKILL.md references must live inside that
plugin's own folder. Shared content is therefore authored once under shared/ and copied
into each plugin that lists it in plugins/<name>/shared.manifest.

The copies are committed, because `copilot plugin marketplace add` reads the repository
directly -- a plugin missing its materialized files would install broken.

Usage:
    python3 tools/materialize.py            # write the copies
    python3 tools/materialize.py --check    # report drift, write nothing, exit 1 if stale
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(REPO, "shared")
PLUGINS = os.path.join(REPO, "plugins")

BANNER_MD = (
    "<!-- GENERATED FILE -- DO NOT EDIT.\n"
    "     Source: shared/{src}\n"
    "     Regenerate: python3 tools/materialize.py -->\n\n"
)
BANNER_PY = (
    "# GENERATED FILE -- DO NOT EDIT.\n"
    "# Source: shared/{src}\n"
    "# Regenerate: python3 tools/materialize.py\n"
)


def banner_for(rel):
    if rel.endswith(".md"):
        return BANNER_MD.format(src=rel)
    if rel.endswith(".py"):
        return BANNER_PY.format(src=rel)
    return ""


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def manifest_entries(plugin_dir):
    """Return [(src_rel, dest_rel)] from shared.manifest.

    Each line is "<path under shared/> -> <path under the plugin>". A line with no arrow
    copies to the same relative path at the plugin root. Blank lines and # comments ignored.

    Destinations are per-skill, because a SKILL.md resolves its bundled paths relative to
    its own folder -- not the plugin root.
    """
    path = os.path.join(plugin_dir, "shared.manifest")
    if not os.path.isfile(path):
        return []
    entries = []
    for line in read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "->" in line:
            src, _, dest = line.partition("->")
            entries.append((src.strip(), dest.strip()))
        else:
            entries.append((line, line))
    return entries


def contained(root, *parts):
    """Resolve root/parts and return it only if it stays inside root.

    Manifests are checked-in text, but a bad entry -- `../../AGENTS.md`, or an absolute
    path -- would otherwise make write mode clobber a file outside the plugin, or copy a
    source from outside shared/. Refuse instead of trusting the path.
    """
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, *parts))
    if target == base or target.startswith(base + os.sep):
        return target
    return None


def render(rel):
    """The exact bytes the materialized copy should contain."""
    src = os.path.join(SHARED, rel)
    if not os.path.isfile(src):
        raise FileNotFoundError("shared/%s does not exist" % rel)
    if contained(SHARED, rel) is None:
        raise ValueError("source %r escapes shared/" % rel)
    body = read(src)
    if rel.endswith(".py") and body.startswith("#!"):
        shebang, _, remainder = body.partition("\n")
        return shebang + "\n" + banner_for(rel) + remainder
    return banner_for(rel) + body


def plugin_dirs():
    if not os.path.isdir(PLUGINS):
        return []
    return sorted(
        os.path.join(PLUGINS, name)
        for name in os.listdir(PLUGINS)
        if os.path.isdir(os.path.join(PLUGINS, name))
    )


def run(check):
    stale, written, problems = [], [], []

    for plugin_dir in plugin_dirs():
        plugin = os.path.basename(plugin_dir)
        for src_rel, dest_rel in manifest_entries(plugin_dir):
            dest = contained(plugin_dir, dest_rel)
            if dest is None:
                problems.append("%s: destination %r escapes the plugin directory"
                                % (plugin, dest_rel))
                continue
            try:
                expected = render(src_rel)
            except (FileNotFoundError, ValueError) as exc:
                problems.append("%s: %s" % (plugin, exc))
                continue

            current = read(dest) if os.path.isfile(dest) else None
            if current == expected:
                continue

            if check:
                reason = "missing" if current is None else "out of date"
                stale.append("%s/%s (%s)" % (plugin, dest_rel, reason))
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(expected)
                if dest_rel.endswith(".py"):
                    os.chmod(dest, 0o755)
                written.append("%s/%s" % (plugin, dest_rel))

    for line in problems:
        print("ERROR %s" % line)

    if check:
        for line in stale:
            print("STALE %s" % line)
        if stale or problems:
            print("\n%d stale, %d error(s). Run: python3 tools/materialize.py"
                  % (len(stale), len(problems)))
            return 1
        print("materialize: all copies up to date")
        return 0

    for line in written:
        print("wrote %s" % line)
    if problems:
        return 1
    print("materialize: %d file(s) written" % len(written))
    return 0


if __name__ == "__main__":
    sys.exit(run(check="--check" in sys.argv[1:]))
