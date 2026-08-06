#!/usr/bin/env python3
"""Structural checks for this marketplace. Standard library only.

    python3 tools/validate.py

Exits 0 when everything passes, 1 otherwise. Every failure names the file and what is wrong.
"""

import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(REPO, "plugins")
MARKETPLACE = os.path.join(REPO, ".github", "plugin", "marketplace.json")
README = os.path.join(REPO, "README.md")
SKILL_LINE_BUDGET = 500

FAILURES = []


def fail(where, message):
    FAILURES.append("%s: %s" % (where, message))


def rel(path):
    return os.path.relpath(path, REPO)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_json(path):
    try:
        return json.loads(read(path))
    except ValueError as exc:
        fail(rel(path), "does not parse as JSON (%s)" % exc)
    except OSError as exc:
        fail(rel(path), "cannot be read (%s)" % exc)
    return None


def parse_frontmatter(text):
    """Minimal YAML frontmatter reader: top-level `key: value`, folded continuations.

    Deliberately not PyYAML -- this repo stays stdlib-only. Skill frontmatter is two
    scalar fields, which does not justify a dependency.
    """
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        return None
    fields, key = {}, None
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        header = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if header:
            key = header.group(1)
            fields[key] = header.group(2).strip()
        elif key and (line.startswith("  ") or line.startswith("\t")):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


def is_plugin(name):
    return not name.startswith("_") and not name.startswith(".")


def plugin_names():
    if not os.path.isdir(PLUGINS):
        return []
    return sorted(
        name for name in os.listdir(PLUGINS)
        if os.path.isdir(os.path.join(PLUGINS, name)) and is_plugin(name)
    )


def check_plugin(name):
    plugin_dir = os.path.join(PLUGINS, name)
    manifest_path = os.path.join(plugin_dir, ".github", "plugin", "plugin.json")

    if not os.path.isfile(manifest_path):
        fail("plugins/%s" % name, "has no .github/plugin/plugin.json")
        return None

    manifest = load_json(manifest_path)
    if manifest is None:
        return None

    if manifest.get("name") != name:
        fail(rel(manifest_path), "name is %r but the folder is %r"
             % (manifest.get("name"), name))

    for field in ("description", "version"):
        if not manifest.get(field):
            fail(rel(manifest_path), "missing required field %r" % field)

    skills = manifest.get("skills") or []
    if not skills:
        fail(rel(manifest_path), "declares no skills")

    for entry in skills:
        skill_dir = os.path.normpath(os.path.join(plugin_dir, entry))
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            fail(rel(manifest_path), "skills entry %r has no SKILL.md" % entry)
            continue
        check_skill(name, skill_dir, skill_md)

    declared = {os.path.basename(os.path.normpath(e)) for e in skills}
    skills_root = os.path.join(plugin_dir, "skills")
    if os.path.isdir(skills_root):
        for found in sorted(os.listdir(skills_root)):
            if os.path.isdir(os.path.join(skills_root, found)) and found not in declared:
                fail("plugins/%s/skills/%s" % (name, found),
                     "exists but is not listed in plugin.json skills[] -- it will not install")

    return manifest


def check_skill(plugin, skill_dir, skill_md):
    where = rel(skill_md)
    text = read(skill_md)

    fields = parse_frontmatter(text)
    if fields is None:
        fail(where, "has no YAML frontmatter")
        return

    folder = os.path.basename(skill_dir)
    if fields.get("name") != folder:
        fail(where, "frontmatter name is %r but the folder is %r"
             % (fields.get("name"), folder))
    if not fields.get("description"):
        fail(where, "frontmatter has no description")

    lines = len(text.splitlines())
    if lines > SKILL_LINE_BUDGET:
        fail(where, "is %d lines, over the %d-line budget -- move detail to references/"
             % (lines, SKILL_LINE_BUDGET))

    plugin_root = os.path.join(PLUGINS, plugin)
    for link in local_links(text):
        target = os.path.normpath(os.path.join(skill_dir, link))
        if not os.path.exists(target):
            fail(where, "links to %r which does not exist" % link)
        elif not target.startswith(plugin_root + os.sep):
            fail(where, "links to %r, outside the plugin -- dead once installed" % link)

    # Bundled resources are cited as code spans, not markdown links -- `references/x.md`.
    # These are the paths the agent actually follows, so they matter more than links.
    for ref in bundled_refs(text):
        target = os.path.normpath(os.path.join(skill_dir, ref))
        if not os.path.exists(target):
            fail(where, "cites bundled resource %r which does not exist" % ref)
        elif not target.startswith(plugin_root + os.sep):
            fail(where, "cites %r, outside the plugin -- dead once installed" % ref)


def local_links(text):
    """Relative markdown link targets, ignoring URLs, anchors, and code fences."""
    without_code = re.sub(r"```.*?```", "", text, flags=re.S)
    links = []
    for target in re.findall(r"\]\(([^)]+)\)", without_code):
        target = target.split("#")[0].strip()
        if target and not target.startswith(("http://", "https://", "mailto:", "#")):
            links.append(target)
    return links


BUNDLED_DIRS = ("references", "scripts", "assets")


def bundled_refs(text):
    """Paths inside code spans that point at a skill's bundled directories.

    A SKILL.md cites `references/foo.md` and `scripts/bar.py` as code, not as links, so
    link checking alone leaves the most load-bearing paths unverified.
    """
    refs = set()
    for span in re.findall(r"`([^`\n]+)`", text):
        span = span.strip()
        if span.startswith(BUNDLED_DIRS) and "/" in span and " " not in span:
            refs.add(span)
    return sorted(refs)


def check_marketplace(manifests):
    catalog = load_json(MARKETPLACE)
    if catalog is None:
        return

    entries = {e.get("name"): e for e in catalog.get("plugins", []) if isinstance(e, dict)}

    for name, manifest in manifests.items():
        entry = entries.get(name)
        if entry is None:
            fail(rel(MARKETPLACE), "has no entry for plugin %r" % name)
            continue
        expected_source = "plugins/%s" % name
        if entry.get("source") != expected_source:
            fail(rel(MARKETPLACE), "%s source is %r, expected %r"
                 % (name, entry.get("source"), expected_source))
        for field in ("description", "version"):
            if entry.get(field) != manifest.get(field):
                fail(rel(MARKETPLACE),
                     "%s %s disagrees with plugin.json (%r vs %r)"
                     % (name, field, entry.get(field), manifest.get(field)))

    for name in entries:
        if name not in manifests:
            fail(rel(MARKETPLACE), "lists %r, which is not a plugin directory" % name)


def check_readme(names):
    text = read(README)
    for name in names:
        if not re.search(r"\[`?%s`?\]|\|\s*`?%s`?\s*\|" % (re.escape(name), re.escape(name)), text):
            fail("README.md", "has no catalog row for plugin %r" % name)


def check_repo_links():
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            for link in local_links(read(path)):
                if not os.path.exists(os.path.normpath(os.path.join(dirpath, link))):
                    fail(rel(path), "links to %r which does not exist" % link)


def check_materialized():
    result = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "materialize.py"), "--check"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        for line in (result.stdout + result.stderr).strip().splitlines():
            if line.strip():
                fail("materialize", line.strip())


def main():
    names = plugin_names()
    if not names:
        fail("plugins/", "contains no plugins")

    manifests = {}
    for name in names:
        manifest = check_plugin(name)
        if manifest:
            manifests[name] = manifest

    check_marketplace(manifests)
    check_readme(names)
    check_repo_links()
    check_materialized()

    if FAILURES:
        for line in FAILURES:
            print("FAIL %s" % line)
        print("\n%d problem(s)." % len(FAILURES))
        return 1

    print("OK %d plugin(s), %d skill(s) -- all checks passed"
          % (len(manifests), sum(len(m.get("skills") or []) for m in manifests.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
