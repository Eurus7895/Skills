#!/usr/bin/env python3
"""Detect a repository's ecosystem, test framework, and runner command.

Reads the filesystem only. No network, no writes.

Usage:
    python3 detect_stack.py [REPO_ROOT] [TARGET] [--check-env]

TARGET is the file or directory being worked on. In a monorepo it selects the nearest
enclosing package rather than the first marker found repository-wide.

Prints one JSON object to stdout:

    {"ecosystem": "python", "test_framework": "pytest", "runner_command": "pytest",
     "test_glob": "tests/test_*.py", "confidence": "high", "marker": "pyproject.toml",
     "notes": []}

confidence is "high" (framework named in a manifest and test files match), "low" (a marker
file exists but the framework is a guess), or "none" (nothing recognized).

--check-env adds one extra key, "env", saying whether the runner can actually be invoked
and what it would take to make it invocable. The rest of the object is unchanged, so
callers that do not pass the flag see exactly the output they saw before. See check_env().

Exits 0 when confidence is high or low, 1 when none, 2 on a usage error, so callers can
branch on the exit code.
"""

import json
import os
import re
import shutil
import sys

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "venv", ".venv", "build", "dist", "target",
    "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", "third_party",
}

# marker file -> (ecosystem, default framework, default runner, test glob)
MARKERS = [
    ("pyproject.toml", "python", "pytest", "pytest", "tests/test_*.py"),
    ("pytest.ini", "python", "pytest", "pytest", "tests/test_*.py"),
    ("tox.ini", "python", "pytest", "pytest", "tests/test_*.py"),
    ("setup.py", "python", "unittest", "python -m unittest", "tests/test_*.py"),
    ("package.json", "javascript", None, "npm test", "*.test.*"),
    ("go.mod", "go", "testing", "go test ./...", "*_test.go"),
    ("Cargo.toml", "rust", "builtin", "cargo test", "tests/*.rs"),
    ("pom.xml", "java", "junit", "mvn test", "src/test/java/**/*Test.java"),
    ("build.gradle", "java", "junit", "gradle test", "src/test/java/**/*Test.java"),
    ("build.gradle.kts", "java", "junit", "gradle test", "src/test/kotlin/**/*Test.kt"),
    ("CMakeLists.txt", "cpp", None, "ctest", "test/*_test.cpp"),
    ("composer.json", "php", "phpunit", "vendor/bin/phpunit", "tests/*Test.php"),
    ("Gemfile", "ruby", "rspec", "bundle exec rspec", "spec/**/*_spec.rb"),
    ("Package.swift", "swift", "xctest", "swift test", "Tests/**/*Tests.swift"),
]

# dependency name -> (framework, runner) for JS, which cannot be inferred from the marker alone
JS_FRAMEWORKS = [
    ("vitest", "vitest", "npx vitest run"),
    ("jest", "jest", "npx jest"),
    ("mocha", "mocha", "npx mocha"),
    ("@playwright/test", "playwright", "npx playwright test"),
    ("ava", "ava", "npx ava"),
]

PY_FRAMEWORKS = [("pytest", "pytest", "pytest")]


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def find_markers(root):
    """Return {marker_filename: absolute_path} for markers at or near the root."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        depth = os.path.relpath(dirpath, root).count(os.sep)
        if os.path.relpath(dirpath, root) == ".":
            depth = -1
        if depth >= 2:  # markers deeper than this belong to sub-packages
            dirnames[:] = []
            continue
        for name, *_ in MARKERS:
            if name in filenames and name not in found:
                found[name] = os.path.join(dirpath, name)
    return found


def has_test_files(root, patterns):
    """True if any file under root matches one of the regex patterns."""
    if not patterns:
        return False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            for pat in patterns:
                if re.search(pat, fn):
                    return True
    return False


def has_rust_tests(root):
    """Rust tests are a tests/ directory or an inline #[cfg(test)] module."""
    if os.path.isdir(os.path.join(root, "tests")):
        return True
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".rs") and "#[cfg(test)]" in read(os.path.join(dirpath, fn)):
                return True
    return False


# Ecosystems whose framework is genuinely implied by the marker file, so the hard-coded
# default is evidence rather than a guess. Everywhere else the default stays low
# confidence until a manifest or config names the framework.
SELF_EVIDENT = {"go", "rust"}


def manifest_names_framework(ecosystem, marker_path, framework):
    """True when the ecosystem's manifest actually mentions the framework."""
    if not framework:
        return False
    if ecosystem in SELF_EVIDENT:
        return True
    haystack = read(marker_path).lower()
    if ecosystem == "ruby":
        for name, fw in (("rspec", "rspec"), ("minitest", "minitest")):
            if name in haystack:
                return fw == framework
        return False
    return framework.lower() in haystack


RUBY_RUNNERS = {"rspec": "bundle exec rspec", "minitest": "bundle exec rake test"}


TEST_FILE_PATTERNS = {
    "python": [r"^test_.*\.py$", r".*_test\.py$"],
    "javascript": [r"\.(test|spec)\.[jt]sx?$"],
    "go": [r"_test\.go$"],
    # Rust has no test-file naming convention: tests live in tests/ or in inline
    # #[cfg(test)] modules. Matching *.rs would count every source file as a test.
    "rust": [],
    "java": [r"Test[s]?\.(java|kt)$"],
    "cpp": [r"_test\.(cpp|cc|cxx)$", r"^test_.*\.(cpp|cc|cxx)$"],
    "php": [r"Test\.php$"],
    "ruby": [r"_spec\.rb$", r"_test\.rb$"],
    "swift": [r"Tests?\.swift$"],
    "csharp": [r"Tests?\.cs$"],
}


def detect_javascript(path, notes):
    content = read(path)
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        notes.append("package.json did not parse; falling back to text search")
        data = {}
    deps = {}
    for key in ("dependencies", "devDependencies"):
        value = data.get(key)
        if isinstance(value, dict):
            deps.update(value)
    for dep, framework, runner in JS_FRAMEWORKS:
        if dep in deps:
            scripts = data.get("scripts")
            if isinstance(scripts, dict) and "test" in scripts:
                return framework, "npm test", "high"
            return framework, runner, "high"
    scripts = data.get("scripts")
    if isinstance(scripts, dict) and "test" in scripts:
        notes.append("no known framework in dependencies; using the declared test script")
        return None, "npm test", "low"
    return None, "npm test", "low"


def detect_python(path, notes):
    content = read(path)
    for dep, framework, runner in PY_FRAMEWORKS:
        if re.search(r"\b%s\b" % re.escape(dep), content):
            return framework, runner, "high"
    if os.path.basename(path) == "setup.py":
        return "unittest", "python -m unittest", "low"
    notes.append("no framework named in %s; assuming pytest" % os.path.basename(path))
    return "pytest", "pytest", "low"


def detect_cpp(path, notes):
    content = read(path)
    lowered = content.lower()
    if "gtest" in lowered or "googletest" in lowered:
        return "googletest", "ctest", "high"
    if "catch2" in lowered or "catch.hpp" in lowered:
        return "catch2", "ctest", "high"
    if "doctest" in lowered:
        return "doctest", "ctest", "high"
    if "enable_testing" in lowered or "add_test" in lowered:
        notes.append("CTest is enabled but no framework was named")
        return None, "ctest", "low"
    return None, "ctest", "low"


def find_csproj(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".csproj"):
                return os.path.join(dirpath, fn)
        if os.path.relpath(dirpath, root).count(os.sep) >= 1:
            dirnames[:] = []
    return None


def nearest_marker(target, boundary=None):
    """Walk up from target to the closest directory holding a marker file.

    In a monorepo the answer depends on which package you are working in: a root
    pyproject.toml alongside a nested Vitest package must not report pytest for a file
    inside that package. The nearest enclosing marker wins.

    `boundary` stops the walk. Without it a repository containing no marker but nested
    inside another project would resolve to the parent, and --check-env would then report
    an install command for dependencies and files outside the directory the caller named.
    """
    names = [name for name, *_ in MARKERS]
    current = os.path.abspath(target)
    if os.path.isfile(current):
        current = os.path.dirname(current)
    stop = os.path.abspath(boundary) if boundary else None
    while True:
        for name in names:
            if os.path.isfile(os.path.join(current, name)):
                return current, name
        if stop is not None and current == stop:
            return None, None
        parent = os.path.dirname(current)
        if parent == current:
            return None, None
        current = parent


# ---------------------------------------------------------------------------
# Environment check (--check-env)
# ---------------------------------------------------------------------------

# Ecosystem -> the executable that provides its test runner. These runners are part of a
# language toolchain rather than a package, so no package manager can install them. Their
# presence still has to be verified: finding go.mod proves the repository is Go, not that
# Go is installed on this machine.
BUILTIN_TOOLCHAIN = {"go": "go", "rust": "cargo", "swift": "swift"}

# Frameworks that are part of their language's standard library. Nothing to install, and
# nothing to look for on PATH -- `pip install unittest` would fetch an unrelated package
# abandoned in 2007.
STDLIB_FRAMEWORKS = {"unittest"}

# Ecosystems where installing a test framework means hand-editing a build file (pom.xml,
# build.gradle, CMakeLists.txt, a .csproj) or driving a package manager whose failure
# modes are not worth guessing at. No install is ever proposed for these -- but the runner
# they already have still has to be looked for, because a caller that gates on
# `available` would otherwise treat every working Maven project as unusable.
MANUAL_INSTALL = {"java", "cpp", "php", "ruby", "csharp"}

# lockfile -> package manager, most specific first. bun.lock is the text lockfile written
# by Bun 1.2 and later; bun.lockb is the older binary one and is still found in the wild.
PY_LOCKFILES = [("uv.lock", "uv"), ("poetry.lock", "poetry"), ("Pipfile.lock", "pipenv")]
JS_LOCKFILES = [
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lock", "bun"),
    ("bun.lockb", "bun"),
    ("package-lock.json", "npm"),
]

# manager -> how to install from a lockfile, how to install without one, and how to add.
#
# `sync` is the variant that provably writes no tracked file: it either installs exactly
# what the lockfile pins or refuses. That is what lets the sync action carry an empty
# `modifies` list, which is what keeps its consent at notify rather than ask.
#
#   uv sync --locked --inexact
#                           --locked asserts uv.lock will remain unchanged (bare
#                           `uv sync` may rewrite it when the manifest has drifted);
#                           --inexact stops it removing packages that are in the
#                           environment but not the lockfile. Without it a "nothing is
#                           rewritten" sync can still uninstall someone's work.
#   poetry install          refuses with "pyproject.toml changed significantly" rather
#                           than regenerating poetry.lock
#   npm ci / --frozen-lockfile
#                           install from the lockfile only, and fail if it is absent
#
# `create` is the fallback used when no lockfile exists yet. It necessarily writes one, so
# it reports that file in `modifies` and is escalated to ask.
MANAGERS = {
    "uv": {
        "lockfile": "uv.lock", "manifest": "pyproject.toml",
        "sync": "uv sync --locked --inexact", "create": "uv sync",
        "add": "uv add --dev %s",
    },
    "poetry": {
        "lockfile": "poetry.lock", "manifest": "pyproject.toml",
        "sync": "poetry install", "create": "poetry install",
        "add": "poetry add --group dev %s",
    },
    "pipenv": {
        "lockfile": "Pipfile.lock", "manifest": "Pipfile",
        "sync": "pipenv sync --dev", "create": "pipenv install --dev",
        "add": "pipenv install --dev %s",
    },
    "pip": {
        "lockfile": None, "manifest": None,
        "sync": "pip install %s", "create": "pip install %s", "add": "pip install %s",
    },
    "npm": {
        "lockfile": "package-lock.json", "manifest": "package.json",
        "sync": "npm ci", "create": "npm install", "add": "npm install --save-dev %s",
    },
    "pnpm": {
        "lockfile": "pnpm-lock.yaml", "manifest": "package.json",
        "sync": "pnpm install --frozen-lockfile", "create": "pnpm install",
        "add": "pnpm add -D %s",
    },
    "yarn": {
        "lockfile": "yarn.lock", "manifest": "package.json",
        "sync": "yarn install --frozen-lockfile", "create": "yarn install",
        "add": "yarn add -D %s",
    },
    "bun": {
        "lockfile": "bun.lock", "manifest": "package.json",
        "sync": "bun install --frozen-lockfile", "create": "bun install",
        "add": "bun add -d %s",
    },
}

# framework -> the executable it installs, where the two differ
BINARIES = {"playwright": "playwright"}

# Managers that own a project-local environment. For these, a runner on PATH is not an
# answer: a global pytest run against a uv project cannot see the project's dependencies
# and dies on ImportError rather than on "command not found". Only the project's own
# environment counts.
ISOLATED_MANAGERS = {"uv", "poetry", "pipenv", "npm", "pnpm", "yarn", "bun"}


def executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def manual_runner(root, ecosystem, marker_path):
    """Find the runner of an ecosystem no package manager here will install for.

    A wrapper checked into the repository wins over PATH: `./gradlew` is the version the
    project pins, and a globally installed gradle may not be it.
    """
    marker = os.path.basename(marker_path)
    local, names = [], []
    if ecosystem == "java":
        if marker.startswith("build.gradle"):
            local, names = ["gradlew", "gradlew.bat"], ["gradle"]
        else:
            local, names = ["mvnw", "mvnw.cmd"], ["mvn"]
    elif ecosystem == "csharp":
        names = ["dotnet"]
    elif ecosystem == "ruby":
        names = ["bundle", "bundler"]
    elif ecosystem == "php":
        local, names = [os.path.join("vendor", "bin", "phpunit")], ["phpunit"]
    elif ecosystem == "cpp":
        names = ["ctest"]
    for rel in local:
        if executable(os.path.join(root, rel)):
            return os.path.join(".", rel)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def declared_manager(root):
    """The manager named by package.json's "packageManager" field, if any.

    Corepack treats that field as authoritative. Ignoring it and defaulting to npm turns a
    lockfile-less pnpm project into `npm install`, which writes a package-lock.json that
    conflicts with the manager the project actually uses.
    """
    path = os.path.join(root, "package.json")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            spec = json.load(fh).get("packageManager")
    except (OSError, ValueError):
        return None
    if isinstance(spec, str):
        name = spec.split("@", 1)[0].strip().lower()
        if name in MANAGERS:
            return name
    return None


def package_manager(package_root, repo_root, ecosystem):
    """Return (manager, lockfile_dir, lockfile_name), searching up to repo_root.

    The lockfile is looked for from the package outwards because a workspace keeps one
    lockfile at its root and only a package.json in each member. Stopping at the package
    would find nothing in a normal pnpm monorepo, fall back to npm, and recommend `npm ci`
    for a project pnpm owns.
    """
    table = PY_LOCKFILES if ecosystem == "python" else JS_LOCKFILES
    current = os.path.abspath(package_root)
    stop = os.path.abspath(repo_root)
    while True:
        for lockfile, manager in table:
            if os.path.isfile(os.path.join(current, lockfile)):
                return manager, current, lockfile
        parent = os.path.dirname(current)
        if current == stop or parent == current or not current.startswith(stop + os.sep):
            break
        current = parent
    if ecosystem == "javascript":
        named = declared_manager(package_root)
        if named:
            return named, None, None
    # No lockfile anywhere up to the repository root.
    return ("pip" if ecosystem == "python" else "npm"), None, None


# TOML tables whose entries are dependencies. Anything else -- [tool.pytest.ini_options],
# [build-system], a comment, the project name -- is configuration, not a declaration that
# the package will be installed.
#
# The captured group is what the sync command has to select. `uv sync` installs the main
# dependencies and the default dependency group; an extra or a non-default group is not
# installed unless it is named, so a declaration found in one of those tables produces a
# sync that completes without installing anything.
PY_DEP_TABLES = [
    (re.compile(r"^project\.optional-dependencies$", re.I), "extra"),
    (re.compile(r"^dependency-groups$", re.I), "group"),
    (re.compile(r"^tool\.poetry\.(?:dev-)?dependencies$", re.I), None),
    (re.compile(r"^tool\.poetry\.group\.([^.\]]+)\.dependencies$", re.I), "poetry-group"),
    (re.compile(r"^tool\.pdm\.dev-dependencies$", re.I), "group"),
    (re.compile(r"^tool\.uv\.dev-dependencies$", re.I), None),
    (re.compile(r"^tool\.hatch\.envs\.[^.\]]+$", re.I), None),
]


def declared_in_toml(text, framework):
    """Where `framework` is declared, or None.

    Returns (selector_kind, selector_name) so the caller can build a command that actually
    installs it. A pyproject.toml that only carries [tool.pytest.ini_options] configures
    pytest without asking for it to be installed, and reading that as a declaration sends
    the caller to a sync command that cannot install the runner.
    """
    pattern = re.compile(r"\b%s\b" % re.escape(framework), re.I)
    section = ""
    in_project_deps = False
    key = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]").strip()
            in_project_deps = False
            key = None
            continue
        if section.lower() == "project":
            # [project] holds dependencies = [...] among unrelated keys, so track whether
            # the current line is still inside that array.
            if re.match(r"dependencies\s*=", line):
                in_project_deps = True
            elif re.match(r"[A-Za-z0-9_.\"'-]+\s*=", line):
                in_project_deps = False
            if in_project_deps and pattern.search(line):
                return (None, None)
            continue

        kind = None
        matched = False
        for expr, sel in PY_DEP_TABLES:
            hit = expr.match(section)
            if hit:
                matched = True
                kind = sel
                if sel == "poetry-group":
                    key = hit.group(1)
                break
        if not matched:
            continue

        # Inside a table keyed by extra or group name, the key on the left of `=` is that
        # name: `test = ["pytest"]`.
        if kind in ("extra", "group"):
            assignment = re.match(r"([A-Za-z0-9_.\"'-]+)\s*=", line)
            if assignment:
                key = assignment.group(1).strip("\"'")
        if pattern.search(line):
            if kind == "poetry-group":
                return ("poetry-group", key)
            if kind in ("extra", "group"):
                return (kind, key)
            return (None, None)
    return None


def declared_in_package_json(path, framework):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    names = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = data.get(key)
        if isinstance(value, dict):
            names.update(value)
    if framework == "playwright":
        return "@playwright/test" in names or "playwright" in names
    return framework in names


def requirements_declaring(root, framework):
    """The requirements file that names `framework`, or None.

    The file matters, not just the fact: it usually pins a version, and installing a bare
    `pytest` against a project that asks for `pytest<8` produces test results from an
    environment the project never described.
    """
    if not os.path.isdir(root):
        return None
    for name in sorted(os.listdir(root)):
        if name.startswith("requirements") and name.endswith(".txt"):
            if re.search(r"^\s*%s\b" % re.escape(framework),
                         read(os.path.join(root, name)), re.M | re.I):
                return name
    return None


def find_runner(root, ecosystem, framework, manager):
    """Return the command that invokes the runner, or None if it is not installed.

    Filesystem only -- nothing is executed. importlib is not used: it would report on the
    interpreter running this script, which is usually not the project's.

    The returned value matters as much as the boolean. A project virtualenv that is not
    activated holds a perfectly good pytest that the bare command `pytest` will not reach,
    so the caller needs the qualified path rather than `runner_command`.
    """
    binary = BINARIES.get(framework, framework)
    if not binary:
        return None

    if ecosystem == "javascript":
        # Windows package managers write .cmd shims beside (or instead of) the POSIX ones.
        for name in (binary, binary + ".cmd"):
            local = os.path.join(root, "node_modules", ".bin", name)
            if executable(local):
                return local
        return None

    for venv in (".venv", "venv"):
        for sub, exe in (("bin", binary), ("Scripts", binary + ".exe")):
            local = os.path.join(root, venv, sub, exe)
            if executable(local):
                return local
    if manager in ISOLATED_MANAGERS:
        return None
    return shutil.which(binary)


def new_env():
    return {
        "package_manager": None,
        "declared": False,
        "available": False,
        "invocation": None,
        "working_directory": ".",
        "action": "unknown",
        "command": None,
        "modifies": [],
        "consent": "ask",
        "notes": [],
    }


def sync_command(manager, spec, framework, declaration, root):
    """Build the command that installs an already-declared runner.

    The declaration's location is part of the command, not a detail: `uv sync` skips
    extras and non-default groups, and `pip install pytest` throws away the version a
    requirements file pinned.
    """
    notes = []
    if manager == "pip":
        req = declaration[1] if declaration and declaration[0] == "requirements" else None
        if req:
            return "pip install -r %s" % req, notes
        notes.append("installing %s without the constraint the manifest states -- pip "
                     "cannot read it here, so check the version if it matters" % framework)
        return "pip install %s" % framework, notes

    command = spec["sync"]
    if declaration:
        kind, name = declaration
        if manager == "uv" and kind == "extra" and name:
            command += " --extra %s" % name
        elif manager == "uv" and kind == "group" and name:
            command += " --group %s" % name
        elif manager == "poetry" and kind == "poetry-group" and name:
            command += " --with %s" % name
    if "%s" in command:
        command = command % framework
    return command, notes


def check_env(root, repo_root, ecosystem, framework, marker_path):
    """Report whether the detected runner can be invoked, and what installing it would cost.

    Three states, not two, because "declared but not installed" and "not declared" carry
    very different risk:

      declared + available    -> action none:    nothing to do
      declared + missing      -> action sync:    install what the project already pins
      not declared + missing  -> action add:     introduce a dependency the project lacks

    `consent` follows from the action, and callers must not re-derive it:

      none    -> none    nothing happens
      sync    -> notify  tell the user, then proceed -- unless no lockfile exists yet, in
                         which case the sync has to write one and is escalated to ask
      add     -> ask     always. Adding a dependency is the user's decision even when the
                         command happens to write no file, as with plain pip
      unknown -> ask     the script could not work out a safe command

    `modifies` lists the tracked files the command rewrites, relative to the repository
    root, and `working_directory` is where the command must run. Both matter in a
    workspace: `uv add` run from the wrong directory edits the root manifest instead of
    the package's, and consent would then have covered the wrong file.
    """
    env = new_env()
    workdir = os.path.relpath(root, repo_root)
    env["working_directory"] = "." if workdir == os.curdir else workdir

    def tracked(name, directory=None):
        """A path relative to the repository root, so consent covers the real file.

        `directory` defaults to the package, but a workspace lockfile lives at the root
        while the manifest being edited lives in the member -- reporting both under the
        member names a lockfile that does not exist.
        """
        where = directory if directory is not None else env["working_directory"]
        return name if where == "." else "%s/%s" % (where.replace(os.sep, "/"), name)

    if ecosystem in BUILTIN_TOOLCHAIN:
        tool = BUILTIN_TOOLCHAIN[ecosystem]
        path = shutil.which(tool)
        env["declared"] = True
        if path:
            env.update(available=True, invocation=path, action="none", consent="none")
            env["notes"].append("the %s toolchain ships its test runner; nothing to install"
                                % ecosystem)
        else:
            env["notes"].append(
                "%r is not on PATH, so the %s toolchain is not installed here. Installing a "
                "language toolchain is outside what this script proposes -- tell the user "
                "what is missing." % (tool, ecosystem))
        return env

    if framework in STDLIB_FRAMEWORKS:
        env.update(declared=True, available=True, action="none", consent="none",
                   invocation="%s -m %s" % (sys.executable, framework))
        env["notes"].append("%s is part of the Python standard library; there is nothing to "
                            "install" % framework)
        return env

    if ecosystem in MANUAL_INSTALL:
        runner = manual_runner(root, ecosystem, marker_path)
        env["declared"] = True
        if runner:
            env.update(available=True, invocation=runner, action="none", consent="none")
            env["notes"].append(
                "%s drives its tests through %s, which is present. Whether every dependency "
                "is fetched is decided by that tool, not here." % (ecosystem, runner))
        else:
            env["notes"].append(
                "no build tool for %s was found, and installing a test framework here means "
                "editing %s by hand; do that with the user rather than automatically"
                % (ecosystem, os.path.basename(marker_path)))
        return env

    if ecosystem not in ("python", "javascript"):
        env["notes"].append("no environment check implemented for %s" % ecosystem)
        return env

    if not framework:
        env["notes"].append("no test framework was detected, so there is nothing to check "
                            "for; resolve the framework first")
        return env

    manager, lock_dir, lockfile = package_manager(root, repo_root, ecosystem)
    spec = MANAGERS[manager]
    env["package_manager"] = manager

    declaration = None
    if ecosystem == "javascript":
        if declared_in_package_json(marker_path, framework):
            declaration = (None, None)
    else:
        if marker_path.endswith(".toml"):
            declaration = declared_in_toml(read(marker_path), framework)
        req = requirements_declaring(root, framework)
        if declaration is None and req:
            declaration = ("requirements", req)
    env["declared"] = declaration is not None

    runner = find_runner(root, ecosystem, framework, manager)
    env["available"] = runner is not None
    if runner:
        env["invocation"] = os.path.relpath(runner, root) if runner.startswith(
            os.path.abspath(root) + os.sep) else runner

    if lock_dir and os.path.abspath(lock_dir) != os.path.abspath(root):
        env["notes"].append("%s belongs to the workspace at %s"
                            % (lockfile, os.path.relpath(lock_dir, repo_root) or "."))

    if env["available"]:
        env.update(action="none", consent="none")
        if not env["declared"]:
            env["notes"].append(
                "%s is installed but not declared in %s; the tests will run here and fail on "
                "a clean checkout" % (framework, os.path.basename(marker_path)))
        return env

    if env["declared"]:
        env["action"] = "sync"
        if lockfile or manager == "pip":
            command, notes = sync_command(manager, spec, framework, declaration, root)
            env["command"] = command
            env["consent"] = "notify"
            env["notes"].extend(notes)
            env["notes"].append("%s is declared in %s but not installed"
                                % (framework, os.path.basename(marker_path)))
        else:
            # Without a lockfile the frozen command has nothing to install from -- `npm ci`
            # exits EUSAGE rather than doing the obvious thing -- so the install has to
            # create one, and creating a tracked file is not a notify-and-proceed change.
            env["command"] = (spec["create"] % framework
                              if "%s" in spec["create"] else spec["create"])
            env["modifies"] = [tracked(spec["lockfile"])] if spec["lockfile"] else []
            # No lockfile was found anywhere, so the one being created lands beside the
            # manifest -- the package directory, not some ancestor.
            env["consent"] = "ask" if env["modifies"] else "notify"
            if spec["lockfile"]:
                env["notes"].append("no %s exists, so the install will create one"
                                    % spec["lockfile"])
        return env

    env["action"] = "add"
    env["consent"] = "ask"
    env["command"] = spec["add"] % framework
    if spec["manifest"]:
        # Listed unconditionally: a lockfile the add command would create is as much a
        # change to the working tree as one it would rewrite.
        env["modifies"] = [tracked(spec["manifest"])]
        if spec["lockfile"]:
            lock_at = (os.path.relpath(lock_dir, repo_root) if lock_dir
                       else env["working_directory"])
            env["modifies"].append(tracked(spec["lockfile"],
                                           "." if lock_at == os.curdir else lock_at))
        env["notes"].append("%s is not declared in %s and is not installed"
                            % (framework, os.path.basename(marker_path)))
    else:
        env["notes"].append(
            "%s is not declared anywhere and this project has no lockfile, so %r would "
            "install it into the environment without declaring it -- a clean checkout would "
            "still have no %s. Settle with the user where the dependency should be recorded."
            % (framework, env["command"], framework))
    return env


def detect(root, target=None, with_env=False, repo_root=None):
    # repo_root stays pinned to the directory the caller named, even when the monorepo
    # recursion narrows `root` to a package. A workspace keeps its lockfile at the top and
    # only a manifest in each member, so the environment check has to be allowed to look
    # above the package it is scoped to.
    if repo_root is None:
        repo_root = root
    notes = []

    if target:
        package_dir, marker_name = nearest_marker(target, boundary=root)
        if package_dir and os.path.abspath(package_dir) != os.path.abspath(root):
            notes.append("scoped to the nearest enclosing package: %s"
                         % os.path.relpath(package_dir, root))
            # Recursing with the package dir as root is what makes --check-env look for
            # node_modules/ and .venv/ beside the package's own manifest, not beside the
            # repository root's.
            result = detect(package_dir, with_env=with_env, repo_root=repo_root)
            result["notes"] = notes + result["notes"]
            return result

    markers = find_markers(root)

    csproj = find_csproj(root)
    if csproj and not markers:
        content = read(csproj).lower()
        framework = None
        for name in ("xunit", "nunit", "mstest"):
            if name in content:
                framework = name
                break
        result = {
            "ecosystem": "csharp",
            "test_framework": framework,
            "runner_command": "dotnet test",
            "test_glob": "*Tests.cs",
            "confidence": "high" if framework else "low",
            "marker": os.path.relpath(csproj, root),
            "notes": notes,
        }
        if with_env:
            result["env"] = check_env(root, repo_root, "csharp", framework, csproj)
        return result

    for name, ecosystem, default_fw, default_runner, glob in MARKERS:
        if name not in markers:
            continue
        path = markers[name]
        framework, runner, confidence = default_fw, default_runner, "low"

        if ecosystem == "javascript":
            framework, runner, confidence = detect_javascript(path, notes)
        elif ecosystem == "python":
            framework, runner, confidence = detect_python(path, notes)
        elif ecosystem == "cpp":
            framework, runner, confidence = detect_cpp(path, notes)
        elif manifest_names_framework(ecosystem, path, default_fw):
            confidence = "high"
        else:
            # The default is a guess, not a detection. Saying "rspec" with high
            # confidence for a Gemfile that declares minitest sends the skill to a
            # runner that may not even be installed.
            if ecosystem == "ruby":
                lowered = read(path).lower()
                if "minitest" in lowered:
                    framework = "minitest"
                    runner = RUBY_RUNNERS["minitest"]
                    confidence = "high"
            if confidence != "high":
                notes.append("%s does not name a test framework; %r is a default, not a detection"
                             % (os.path.basename(path), default_fw))

        found_tests = (has_rust_tests(root) if ecosystem == "rust"
                       else has_test_files(root, TEST_FILE_PATTERNS.get(ecosystem, [])))
        if not found_tests:
            notes.append("no test files found matching the %s convention" % ecosystem)
            if confidence == "high":
                confidence = "low"

        if len(markers) > 1:
            others = sorted(k for k in markers if k != name)
            notes.append("other ecosystem markers present: %s" % ", ".join(others))

        result = {
            "ecosystem": ecosystem,
            "test_framework": framework,
            "runner_command": runner,
            "test_glob": glob,
            "confidence": confidence,
            "marker": os.path.relpath(path, root),
            "notes": notes,
        }
        if with_env:
            result["env"] = check_env(root, repo_root, ecosystem, framework, path)
        return result

    result = {
        "ecosystem": None,
        "test_framework": None,
        "runner_command": None,
        "test_glob": None,
        "confidence": "none",
        "marker": None,
        "notes": ["no recognized ecosystem marker found"],
    }
    if with_env:
        env = new_env()
        env["notes"].append("no ecosystem was detected, so no environment can be checked")
        result["env"] = env
    return result


FLAGS = {"--check-env"}


def main(argv):
    # Unknown flags are refused rather than dropped. Skipping them silently means a typo
    # like --check-eng produces a normal-looking result with no "env" key, which a caller
    # reads as "the environment is fine" -- the one wrong answer that leads to running a
    # test suite against a runner that is not installed.
    flags = set()
    args = []
    for arg in argv[1:]:
        if arg.startswith("-"):
            if arg not in FLAGS:
                print(json.dumps({"error": "unknown option: %s" % arg,
                                  "usage": "detect_stack.py [REPO_ROOT] [TARGET] [%s]"
                                           % " ".join(sorted(FLAGS)),
                                  "confidence": "none"}))
                return 2
            flags.add(arg)
        else:
            args.append(arg)

    if len(args) > 2:
        print(json.dumps({"error": "expected at most REPO_ROOT and TARGET, got %d arguments"
                                   % len(args), "confidence": "none"}))
        return 2

    root = args[0] if args else "."
    target = args[1] if len(args) > 1 else None

    if not os.path.isdir(root):
        print(json.dumps({"error": "not a directory: %s" % root, "confidence": "none"}))
        return 1
    if target and not os.path.exists(target):
        print(json.dumps({"error": "no such target: %s" % target, "confidence": "none"}))
        return 1

    result = detect(root, target, with_env="--check-env" in flags)
    print(json.dumps(result, indent=2))
    return 1 if result["confidence"] == "none" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
