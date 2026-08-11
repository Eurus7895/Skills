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

# Frontmatter `description` + `when_to_use` are concatenated and truncated, silently.
# Sourced from the Claude Code skills reference; GitHub publishes no equivalent for
# Copilot, so treat these as the tightest known bound rather than the platform's.
DESC_WARN = 1024
DESC_LIMIT = 1536

# Anything outside this set makes packaging and upload fail with a hard error rather
# than ignoring the field. `applyTo` belongs to .github/instructions, not to skills --
# instructions bind by path glob, skills bind by description matching.
ALLOWED_FRONTMATTER = {
    "name", "description", "when_to_use", "license",
    "compatibility", "metadata", "allowed-tools",
}

FAILURES = []
WARNINGS = []


def fail(where, message):
    FAILURES.append("%s: %s" % (where, message))


def warn(where, message):
    """Advisory only -- never affects the exit code.

    Reserved for heuristics. A check that can be wrong must not be able to block a
    pull request, or the first false positive gets the whole validator disabled.
    """
    WARNINGS.append("%s: %s" % (where, message))


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

    unexpected = sorted(set(fields) - ALLOWED_FRONTMATTER)
    if unexpected:
        fail(where, "frontmatter has unsupported key(s) %s -- packaging fails hard on "
                    "these rather than ignoring them. Allowed: %s"
             % (", ".join(repr(k) for k in unexpected),
                ", ".join(sorted(ALLOWED_FRONTMATTER))))

    # The description is the only text seen before the skill is selected, and the
    # tail is what gets cut -- which is where the "for X, use Y instead" clause lives.
    desc_len = len(fields.get("description", "")) + len(fields.get("when_to_use", ""))
    if desc_len > DESC_LIMIT:
        fail(where, "description is %d chars, over the %d-char limit -- the tail is "
                    "truncated silently, taking any disambiguation clause with it"
             % (desc_len, DESC_LIMIT))
    elif desc_len > DESC_WARN:
        warn(where, "description is %d chars, past %d -- put the key use case and any "
                    "\"use X instead\" clause first" % (desc_len, DESC_WARN))

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


STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "that", "this",
    "it", "its", "is", "are", "was", "be", "been", "when", "whenever", "use", "uses",
    "user", "users", "says", "asks", "ask", "what", "which", "not", "no", "any", "all",
    "code", "repository", "repo", "file", "files", "instead", "rather", "than", "them",
    "they", "their", "you", "your", "from", "by", "at", "as", "so", "if", "one", "each",
}


def significant_ngrams(text, n=3):
    """Content-bearing word n-grams, for comparing what two descriptions claim.

    Quoted-phrase comparison was tried first and is not good enough: review-tests and
    debug-failing-test once both claimed flaky tests in unquoted prose, and a quoted
    scan reported no overlap at all.
    """
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS]
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def collect_skills():
    """(name, path, description) for every skill in a real plugin."""
    found = []
    for plugin in plugin_names():
        skills_dir = os.path.join(PLUGINS, plugin, "skills")
        if not os.path.isdir(skills_dir):
            continue
        for entry in sorted(os.listdir(skills_dir)):
            skill_md = os.path.join(skills_dir, entry, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            fields = parse_frontmatter(read(skill_md)) or {}
            found.append((fields.get("name") or entry, rel(skill_md),
                          fields.get("description", "")))
    return found


def check_skill_collisions():
    """Two skills must not share a name, and should not compete for one request."""
    skills = collect_skills()

    # Exact match, no judgement involved -- a hard failure.
    by_name = {}
    for name, path, _ in skills:
        by_name.setdefault(name, []).append(path)
    for name, paths in sorted(by_name.items()):
        if len(paths) > 1:
            fail("plugins/", "skill name %r is defined in %d places (%s) -- names are "
                             "global once installed, so both entries compete and cost "
                             "listing budget twice" % (name, len(paths), ", ".join(paths)))

    # Trigger similarity is a judgement call, so it only ever warns.
    # Keyed by path, not name: duplicate names would otherwise collapse into one entry
    # and the comparison would match a description against itself.
    grams = {path: significant_ngrams(desc) for _, path, desc in skills}
    for i, (name_a, path_a, _) in enumerate(skills):
        for name_b, path_b, _ in skills[i + 1:]:
            shared = grams[path_a] & grams[path_b]
            if len(shared) >= 2:
                sample = ", ".join(repr(s) for s in sorted(shared)[:3])
                warn(path_a, "description overlaps %r on %d phrase(s): %s -- if both "
                             "could match one request, add a \"for X, use Y instead\" "
                             "clause to each" % (name_b, len(shared), sample))


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


# `copilot plugin install <plugin>@<marketplace>` -- the marketplace half is an
# identifier users type verbatim, so a rename that misses a doc sends them to a
# marketplace that does not exist. Only the `@` form is checked: the troubleshooting
# table deliberately names the *old* marketplace in a `remove` command.
INSTALL_REF = re.compile(r"plugin install\s+\S+?@([A-Za-z0-9_.-]+)")


def check_marketplace_name():
    catalog = load_json(MARKETPLACE)
    if catalog is None:
        return
    expected = catalog.get("name")
    if not expected:
        fail(rel(MARKETPLACE), "has no name")
        return

    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            for found in set(INSTALL_REF.findall(read(path))):
                if found != expected:
                    fail(rel(path), "installs from marketplace %r, but the manifest "
                                    "is named %r" % (found, expected))


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


def check_tracked():
    """Every file the repo depends on must be committed, not just present locally.

    A .gitignore rule once swallowed plugins/*/shared.manifest: the working tree looked
    fine and every check passed, while a fresh clone had no manifests at all.
    """
    result = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
        cwd=REPO, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return  # not a git checkout; nothing to verify

    ignored = set(result.stdout.split())
    required = []
    for name in plugin_names():
        required.append("plugins/%s/shared.manifest" % name)
    for dirpath, dirnames, filenames in os.walk(os.path.join(REPO, "shared")):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            required.append(rel(os.path.join(dirpath, fn)))

    for path in required:
        if not os.path.exists(os.path.join(REPO, path)):
            continue
        if path in ignored:
            fail(path, "is matched by .gitignore -- it will be missing from a fresh clone")


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
    check_marketplace_name()
    check_skill_collisions()
    check_readme(names)
    check_repo_links()
    check_tracked()
    check_materialized()

    for line in WARNINGS:
        print("WARN %s" % line)
    if WARNINGS:
        print("")

    if FAILURES:
        for line in FAILURES:
            print("FAIL %s" % line)
        print("\n%d problem(s)." % len(FAILURES))
        return 1

    print("OK %d plugin(s), %d skill(s) -- all checks passed%s"
          % (len(manifests),
             sum(len(m.get("skills") or []) for m in manifests.values()),
             " (%d warning(s))" % len(WARNINGS) if WARNINGS else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
