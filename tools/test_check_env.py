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


def run(*args, **kwargs):
    """Invoke the script. path="" runs it with an empty PATH, so `shutil.which` finds
    nothing -- the only way to assert toolchain-presence behaviour without depending on
    what happens to be installed on the machine running the tests."""
    env = None
    if "path" in kwargs:
        env = dict(os.environ, PATH=kwargs.pop("path"))
    proc = subprocess.run([sys.executable, SCRIPT] + list(args),
                          capture_output=True, text=True, env=env)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, {"_unparsed": proc.stdout, "_stderr": proc.stderr}


def write(root, rel, body="", executable=False):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    if executable:
        os.chmod(path, 0o755)


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
    write(root, os.path.join(".venv", "bin", "pytest"), executable=True)

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
    write(root, os.path.join("node_modules", ".bin", "vitest"), executable=True)

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

    # A pnpm workspace: one lockfile at the top, only a manifest in each member. Scoping
    # the lockfile search to the package finds nothing and falls back to npm.
    root = tree("workspace")
    write(root, "package.json", '{"name": "root", "private": true}')
    write(root, "pnpm-lock.yaml")
    write(root, os.path.join("apps", "web", "package.json"),
          '{"devDependencies": {"vitest": "^1"}}')
    write(root, os.path.join("apps", "web", "index.js"), "export const a = 1\n")

    # setup.py resolves to unittest, which is standard library. Treating it as a package
    # produces `pip install unittest`, which fetches an unrelated package abandoned in 2007.
    root = tree("setuppy")
    write(root, "setup.py", "from setuptools import setup\nsetup()\n")
    write(root, os.path.join("tests", "test_a.py"), "")

    # No lockfile: `npm ci` exits EUSAGE, so the install has to create one.
    root = tree("npm-no-lockfile")
    write(root, "package.json", '{"devDependencies": {"vitest": "^1"}}')

    # Bun 1.2+ writes the text lockfile bun.lock; bun.lockb is the legacy binary one.
    for name, lockfile in (("bun-text", "bun.lock"), ("bun-legacy", "bun.lockb")):
        root = tree(name)
        write(root, "package.json", '{"devDependencies": {"vitest": "^1"}}')
        write(root, lockfile)

    # pytest configured but never depended on. The name is in the file; it is not declared.
    root = tree("pytest-config-only")
    write(root, "pyproject.toml",
          '[project]\nname = "x"\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    write(root, "uv.lock")

    # The name "pytest" all over the file, in no dependency table: the project is itself
    # a pytest plugin, coverage omits a pytest path, and pytest is configured. None of that
    # is a dependency declaration.
    root = tree("pytest-named-not-declared")
    write(root, "pyproject.toml",
          '[project]\nname = "pytest-sugar-clone"\ndescription = "adds pytest markers"\n'
          '[tool.coverage.run]\nomit = ["*/pytest/*"]\n'
          '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    write(root, "uv.lock")

    # Declared in [project].dependencies, which sits among unrelated keys in that table.
    root = tree("project-dependencies")
    write(root, "pyproject.toml",
          '[project]\nname = "x"\nversion = "0.1.0"\n'
          'dependencies = [\n  "requests",\n  "pytest",\n]\n'
          'requires-python = ">=3.9"\n')
    write(root, "uv.lock")

    # Declared in a requirements file rather than in pyproject.toml.
    root = tree("requirements")
    write(root, "pyproject.toml", PYPROJECT_BARE)
    write(root, "requirements-dev.txt", "pytest>=7\n")

    # A file at .venv/bin/pytest that is not executable is not a runner.
    root = tree("venv-not-executable")
    write(root, "pyproject.toml", PYPROJECT_WITH_PYTEST)
    write(root, "uv.lock")
    write(root, os.path.join(".venv", "bin", "pytest"))
    os.chmod(os.path.join(root, ".venv", "bin", "pytest"), 0o644)

    return roots


# case -> the (action, consent, package_manager) it must report
EXPECTED = {
    "uv-installed":            ("none",    "none",   "uv"),
    "uv-declared-missing":     ("sync",    "notify", "uv"),
    "uv-undeclared":           ("add",     "ask",    "uv"),
    "poetry-declared-missing": ("sync",    "notify", "poetry"),
    "pnpm-declared-missing":   ("sync",    "notify", "pnpm"),
    "pnpm-installed":          ("none",    "none",   "pnpm"),
    "java":                    ("unknown", "ask",    None),
    "empty":                   ("unknown", "ask",    None),
    "setuppy":                 ("none",    "none",   None),
    "npm-no-lockfile":         ("sync",    "ask",    "npm"),
    "bun-text":                ("sync",    "notify", "bun"),
    "bun-legacy":              ("sync",    "notify", "bun"),
    "pytest-config-only":      ("add",     "ask",    "uv"),
    "venv-not-executable":     ("sync",    "notify", "uv"),
}

# "go" and "requirements" are deliberately absent: both depend on what is installed on the
# machine running the tests (the Go toolchain, a global pytest on PATH), so they are
# asserted against that reality further down rather than pinned to one answer here.


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

        # A toolchain-provided runner still has to exist on this machine. Finding go.mod
        # proves the repository is Go, not that Go is installed.
        _, out = run(roots["go"], "--check-env")
        go_installed = shutil.which("go") is not None
        check("go -> availability tracks whether the toolchain is on PATH",
              out["env"]["available"] is go_installed,
              "go on PATH: %s, reported available: %s"
              % (go_installed, out["env"]["available"]))
        check("go -> a missing toolchain is not proposed for installation",
              go_installed or out["env"]["action"] == "unknown",
              "got %r" % out["env"]["action"])

        # unittest is standard library. Routing it through the package-manager path yields
        # `pip install unittest`, which fetches an unrelated package abandoned in 2007.
        _, out = run(roots["setuppy"], "--check-env")
        check("setup.py -> unittest needs no install",
              out["test_framework"] == "unittest" and out["env"]["command"] is None,
              "framework %r, command %r"
              % (out["test_framework"], out["env"]["command"]))

        # A dependency stated in a requirements file is declared, wherever pytest is.
        _, out = run(roots["requirements"], "--check-env")
        check("requirements-dev.txt counts as a declaration",
              out["env"]["declared"] is True, "got %r" % out["env"]["declared"])

        # With nothing on PATH the Go toolchain cannot be found, whatever the machine
        # running these tests happens to have installed.
        _, out = run(roots["go"], "--check-env", path="")
        check("go -> an absent toolchain is reported absent",
              out["env"]["available"] is False, "got %r" % out["env"]["available"])
        check("go -> an absent toolchain yields no install command",
              out["env"]["action"] == "unknown" and out["env"]["command"] is None,
              "got %r / %r" % (out["env"]["action"], out["env"]["command"]))

        # The name appearing in the file is not the name being depended on.
        _, out = run(roots["pytest-named-not-declared"], "--check-env")
        check("the framework named outside a dependency table is not declared",
              out["env"]["declared"] is False, "got %r" % out["env"]["declared"])

        # ...and the converse: it must still be found inside [project].dependencies,
        # which holds unrelated keys before and after the array.
        _, out = run(roots["project-dependencies"], "--check-env")
        check("[project].dependencies counts as a declaration",
              out["env"]["declared"] is True, "got %r" % out["env"]["declared"])

        # Configuring a tool is not depending on it. Reading [tool.pytest.ini_options] as a
        # declaration sends the caller to a sync that cannot install the runner.
        _, out = run(roots["pytest-config-only"], "--check-env")
        check("[tool.pytest.ini_options] alone is not a declaration",
              out["env"]["declared"] is False, "got %r" % out["env"]["declared"])

        # `npm ci` exits EUSAGE with no lockfile, so the remediation has to create one --
        # and creating a tracked file is not a notify-and-proceed change.
        _, out = run(roots["npm-no-lockfile"], "--check-env")
        check("npm without a lockfile is not told to run npm ci",
              out["env"]["command"] == "npm install",
              "got %r" % out["env"]["command"])
        check("npm without a lockfile reports the lockfile it would create",
              out["env"]["modifies"] == ["package-lock.json"],
              "got %r" % (out["env"]["modifies"],))

        # A sync must never be able to rewrite the lockfile it installs from.
        _, out = run(roots["uv-declared-missing"], "--check-env")
        check("uv sync is pinned to the frozen variant",
              out["env"]["command"] == "uv sync --locked",
              "got %r" % out["env"]["command"])

        # An unactivated virtualenv holds a runner the bare command will not reach, so the
        # qualified path is what the caller needs.
        _, out = run(roots["uv-installed"], "--check-env")
        check("an installed runner reports how to invoke it",
              out["env"]["invocation"] == os.path.join(".venv", "bin", "pytest"),
              "got %r" % out["env"]["invocation"])

        # A file that is not executable is not a runner.
        _, out = run(roots["venv-not-executable"], "--check-env")
        check("a non-executable file in .venv/bin is not a runner",
              out["env"]["available"] is False, "got %r" % out["env"]["available"])

        # A workspace keeps one lockfile at the top and only a manifest in each member.
        # Scoping the search to the package finds nothing and falls back to npm.
        _, out = run(roots["workspace"],
                     os.path.join(roots["workspace"], "apps", "web", "index.js"),
                     "--check-env")
        check("a workspace lockfile above the package is found",
              out["env"]["package_manager"] == "pnpm",
              "got %r" % out["env"]["package_manager"])

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
