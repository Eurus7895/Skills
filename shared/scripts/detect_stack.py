#!/usr/bin/env python3
"""Detect a repository's ecosystem, test framework, and runner command.

Reads the filesystem only. No network, no writes.

Usage:
    python3 detect_stack.py [REPO_ROOT] [TARGET]

TARGET is the file or directory being worked on. In a monorepo it selects the nearest
enclosing package rather than the first marker found repository-wide.

Prints one JSON object to stdout:

    {"ecosystem": "python", "test_framework": "pytest", "runner_command": "pytest",
     "test_glob": "tests/test_*.py", "confidence": "high", "marker": "pyproject.toml",
     "notes": []}

confidence is "high" (framework named in a manifest and test files match), "low" (a marker
file exists but the framework is a guess), or "none" (nothing recognized).

Exits 0 when confidence is high or low, 1 when none, so callers can branch on the exit code.
"""

import json
import os
import re
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


def nearest_marker(target):
    """Walk up from target to the closest directory holding a marker file.

    In a monorepo the answer depends on which package you are working in: a root
    pyproject.toml alongside a nested Vitest package must not report pytest for a file
    inside that package. The nearest enclosing marker wins.
    """
    names = [name for name, *_ in MARKERS]
    current = os.path.abspath(target)
    if os.path.isfile(current):
        current = os.path.dirname(current)
    while True:
        for name in names:
            if os.path.isfile(os.path.join(current, name)):
                return current, name
        parent = os.path.dirname(current)
        if parent == current:
            return None, None
        current = parent


def detect(root, target=None):
    notes = []

    if target:
        package_dir, marker_name = nearest_marker(target)
        if package_dir and os.path.abspath(package_dir) != os.path.abspath(root):
            notes.append("scoped to the nearest enclosing package: %s"
                         % os.path.relpath(package_dir, root))
            result = detect(package_dir)
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
        return {
            "ecosystem": "csharp",
            "test_framework": framework,
            "runner_command": "dotnet test",
            "test_glob": "*Tests.cs",
            "confidence": "high" if framework else "low",
            "marker": os.path.relpath(csproj, root),
            "notes": notes,
        }

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

        return {
            "ecosystem": ecosystem,
            "test_framework": framework,
            "runner_command": runner,
            "test_glob": glob,
            "confidence": confidence,
            "marker": os.path.relpath(path, root),
            "notes": notes,
        }

    return {
        "ecosystem": None,
        "test_framework": None,
        "runner_command": None,
        "test_glob": None,
        "confidence": "none",
        "marker": None,
        "notes": ["no recognized ecosystem marker found"],
    }


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    root = args[0] if args else "."
    target = args[1] if len(args) > 1 else None

    if not os.path.isdir(root):
        print(json.dumps({"error": "not a directory: %s" % root, "confidence": "none"}))
        return 1
    if target and not os.path.exists(target):
        print(json.dumps({"error": "no such target: %s" % target, "confidence": "none"}))
        return 1

    result = detect(root, target)
    print(json.dumps(result, indent=2))
    return 1 if result["confidence"] == "none" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
