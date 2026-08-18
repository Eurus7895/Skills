#!/usr/bin/env python3
"""Behavioural tests for detect_stack.py --check-env.

Stdlib only, no test framework -- this repository's scripts must run on a stranger's
machine with no install step, and its own tests should not be the exception.

The trees are built in a temp directory rather than under fixtures/, because these are
package-manager shapes (a lockfile, an empty node_modules/.bin) with no code in them.
fixtures/ holds scenarios a skill is evaluated against; these are not that.

    python3 tools/test_check_env.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "shared", "scripts", "detect_stack.py")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(*args):
    proc = subprocess.run([sys.executable, SCRIPT] + list(args),
                          capture_output=True, text=True)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, {"_unparsed": proc.stdout, "_stderr": proc.stderr}


def write(root, rel, body=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


PYPROJECT_WITH_PYTEST = '[project]\nname = "x"\n[dependency-groups]\ndev = ["pytest"]\n'
PYPROJECT_BARE = '[project]\nname = "x"\n'


def build(tmp):
    """Return {case_name: root}, one directory per environment shape under test."""
    roots = {}

    def tree(name):
        root = os.path.join(tmp, name)
        os.makedirs(root)
        roots[name] = root
        return root

    root = tree("uv-installed")
    write(root, "pyproject.toml", PYPROJECT_WITH_PYTEST)
    write(root, "uv.lock")
    write(root, os.path.join(".venv", "bin", "pytest"))

    root = tree("uv-declared-missing")
    write(root, "pyproject.toml", PYPROJECT_WITH_PYTEST)
    write(root, "uv.lock")

    root = tree("uv-undeclared")
    write(root, "pyproject.toml", PYPROJECT_BARE)
    write(root, "uv.lock")

    root = tree("poetry-declared-missing")
    write(root, "pyproject.toml", '[tool.poetry.group.dev.dependencies]\npytest = "*"\n')
    write(root, "poetry.lock")

    root = tree("pnpm-declared-missing")
    write(root, "package.json", '{"devDependencies": {"vitest": "^1"}}')
    write(root, "pnpm-lock.yaml")

    root = tree("pnpm-installed")
    write(root, "package.json", '{"devDependencies": {"vitest": "^1"}}')
    write(root, "pnpm-lock.yaml")
    write(root, os.path.join("node_modules", ".bin", "vitest"))

    root = tree("go")
    write(root, "go.mod", "module x\n")
    write(root, "x_test.go", "package x\n")

    root = tree("java")
    write(root, "pom.xml", "<project><artifactId>x</artifactId>junit</project>")

    tree("empty")

    root = tree("monorepo")
    write(root, "pyproject.toml", PYPROJECT_WITH_PYTEST)
    write(root, "uv.lock")
    write(root, os.path.join("pkgs", "web", "package.json"),
          '{"devDependencies": {"vitest": "^1"}}')
    write(root, os.path.join("pkgs", "web", "pnpm-lock.yaml"))
    write(root, os.path.join("pkgs", "web", "index.js"), "export const a = 1\n")

    return roots


# case -> the (action, consent, package_manager) it must report
EXPECTED = {
    "uv-installed":            ("none",    "none",   "uv"),
    "uv-declared-missing":     ("sync",    "notify", "uv"),
    "uv-undeclared":           ("add",     "ask",    "uv"),
    "poetry-declared-missing": ("sync",    "notify", "poetry"),
    "pnpm-declared-missing":   ("sync",    "notify", "pnpm"),
    "pnpm-installed":          ("none",    "none",   "pnpm"),
    "go":                      ("none",    "none",   None),
    "java":                    ("unknown", "ask",    None),
    "empty":                   ("unknown", "ask",    None),
}


def main():
    tmp = tempfile.mkdtemp(prefix="check-env-")
    try:
        roots = build(tmp)

        for case, (action, consent, manager) in sorted(EXPECTED.items()):
            _, out = run(roots[case], "--check-env")
            env = out.get("env", {})
            check("%s -> action" % case, env.get("action") == action,
                  "got %r want %r" % (env.get("action"), action))
            check("%s -> consent" % case, env.get("consent") == consent,
                  "got %r want %r" % (env.get("consent"), consent))
            check("%s -> package_manager" % case, env.get("package_manager") == manager,
                  "got %r want %r" % (env.get("package_manager"), manager))

        # An "add" must name every tracked file it would rewrite. That list is the sole
        # input to the consent decision, so an empty one here would silently downgrade a
        # dependency write to a notification.
        _, out = run(roots["uv-undeclared"], "--check-env")
        check("uv-undeclared -> modifies names the manifest and the lockfile",
              out["env"]["modifies"] == ["pyproject.toml", "uv.lock"],
              "got %r" % (out["env"]["modifies"],))
        check("uv-undeclared -> command is the add command",
              out["env"]["command"] == "uv add --dev pytest",
              "got %r" % (out["env"]["command"],))

        # A sync installs what the lockfile already pins, so it must rewrite nothing.
        _, out = run(roots["uv-declared-missing"], "--check-env")
        check("uv-declared-missing -> sync rewrites nothing",
              out["env"]["modifies"] == [], "got %r" % (out["env"]["modifies"],))

        # A global pytest on PATH is not the project's pytest. For a lockfile-managed
        # project it cannot see the project's dependencies, so it must not count as
        # available -- otherwise the skill runs a suite that dies on ImportError.
        check("a PATH-only runner does not satisfy a uv project",
              shutil.which("pytest") is None
              or run(roots["uv-declared-missing"], "--check-env")[1]["env"]["available"] is False,
              "pytest is on PATH and was wrongly accepted")

        # The env check must follow the target into the nearest enclosing package.
        # Reporting the root's uv here would propose a Python install for a JS package.
        _, out = run(roots["monorepo"],
                     os.path.join(roots["monorepo"], "pkgs", "web", "index.js"),
                     "--check-env")
        check("monorepo -> env scopes to the nearest package",
              out["env"]["package_manager"] == "pnpm" and out["ecosystem"] == "javascript",
              "got %r / %r" % (out["env"]["package_manager"], out["ecosystem"]))

        # Without the flag the output must carry no env key at all. Callers written
        # against the previous shape read anything extra as a schema change.
        for case in ("uv-declared-missing", "go", "empty"):
            _, out = run(roots[case])
            check("%s -> no env key without the flag" % case, "env" not in out,
                  "got keys %r" % sorted(out))

        # An unrecognised flag must fail loudly. Dropped silently, a typo produces a
        # normal-looking result with no env key, which reads as "nothing to install".
        code, out = run(roots["uv-declared-missing"], "--check-eng")
        check("an unknown flag exits 2", code == 2, "got exit %d" % code)
        check("an unknown flag names itself", "--check-eng" in out.get("error", ""),
              "got %r" % out.get("error"))

        code, _ = run(roots["uv-declared-missing"], "extra", "args", "here")
        check("too many positional arguments exit 2", code == 2, "got exit %d" % code)

        # --check-env must not disturb the exit code, which callers branch on.
        for case, want in (("uv-declared-missing", 0), ("empty", 1)):
            bare, _ = run(roots[case])
            withenv, _ = run(roots[case], "--check-env")
            check("%s -> exit code unchanged by the flag" % case,
                  bare == withenv == want, "bare %d, --check-env %d" % (bare, withenv))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
