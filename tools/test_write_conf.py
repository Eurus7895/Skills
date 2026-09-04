#!/usr/bin/env python3
"""Behavioural tests for the generated conf.py.

Stdlib only, no test framework -- see tools/test_check_env.py for why.

Generated pages are not a document until something can build them, and a project that
has never used Sphinx has no conf.py to build them with. So this writes one. The risk in
doing that is the obvious one, and it is what most of these tests are about: a generator
that touches somebody's configuration can destroy work no rerun can restore. It writes
once, only when asked, and only when there is nothing there.

    python3 tools/test_write_conf.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "shared", "scripts")

sys.path.insert(0, SCRIPTS)
import sphinx_support                                         # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   %s" % name)
    else:
        print("FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def run(script, *args):
    proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def page(page_id, title, order, text):
    return {"id": page_id, "title": title, "order": order, "mandatory": True,
            "blocks": [{"id": "block:%s" % page_id, "type": "prose", "text": text,
                        "claim_refs": []}]}


def doc_model(tmp, name="doc.json"):
    """A minimal valid document model -- this suite is about conf.py, not content."""
    doc = {"format_version": 1, "generator_version": "test", "preset": "onboarding",
           "source_revision": None, "source_dirty": True,
           "pages": [page("overview", "Overview", 1, "A repository."),
                     page("limitations", "Coverage and limitations", 2, "Very little.")],
           "authored_pages": [], "claims": [], "coverage": {}}
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main():
    tmp = tempfile.mkdtemp(prefix="write-conf-test-")
    try:
        doc = doc_model(tmp)

        # --- The point of the feature: the output builds.
        out = os.path.join(tmp, "docs")
        code, output = run("render_docs.py", "--doc", doc, "--out", out,
                           "--write-conf", "--project", "Order Service",
                           "--author", "Eurus")
        check("rendering with --write-conf succeeds", code == 0, output)
        conf = os.path.join(out, "conf.py")
        check("a conf.py appears beside the pages", os.path.isfile(conf), output)
        check("and the run says what to do with it",
              "sphinx-build" in output, output)

        body = read(conf)
        check("it carries the project name given", "'Order Service'" in body, body)
        check("and the author", "'Eurus'" in body, body)
        check("it says it will never be regenerated",
              "leave it exactly as you leave it" in body, body)

        if shutil.which("sphinx-build"):
            build = subprocess.run(["sphinx-build", "-W", out, os.path.join(out, "_build")],
                                   capture_output=True, text=True)
            check("sphinx-build -W actually builds the generated tree",
                  build.returncode == 0, build.stdout + build.stderr)
            check("and produces the pages",
                  os.path.isfile(os.path.join(out, "_build", "overview.html")))
        else:
            print("ok   (sphinx-build absent: the build itself is not exercised here)")

        # --- The risk. An existing conf.py is somebody's work.
        mine = "# hand-written\nproject = 'Kept'\nextensions = ['myst_parser']\n"
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write(mine)
        code, output = run("render_docs.py", "--doc", doc, "--out", out, "--write-conf")
        check("a second run leaves an existing conf.py byte for byte", read(conf) == mine)
        check("and says so rather than staying silent",
              "kept the existing" in output, output)

        # --- Without the flag, nothing is written -- but the reader is told why the
        #     pages do not build yet, which is not visible from the files.
        bare = os.path.join(tmp, "bare")
        code, output = run("render_docs.py", "--doc", doc, "--out", bare)
        check("no conf.py is written without the flag",
              not os.path.isfile(os.path.join(bare, "conf.py")))
        check("but the run says the pages cannot be built until there is one",
              "cannot be built" in output, output)

        with_conf = os.path.join(tmp, "with-conf")
        os.makedirs(with_conf)
        with open(os.path.join(with_conf, "conf.py"), "w", encoding="utf-8") as fh:
            fh.write("project = 'Theirs'\nextensions = []\n")
        code, output = run("render_docs.py", "--doc", doc, "--out", with_conf)
        check("and stays quiet when the project already has one",
              "cannot be built" not in output, output)

        # --- Extensions follow the pages, not the machine.
        outcome, path = sphinx_support.write_conf(
            os.path.join(tmp, "myst"), ("myst_parser",), "P")
        check("a MyST document declares its parser", outcome == "written" and
              "'myst_parser'" in read(path), outcome)
        check("and says the parser is required, not optional",
              "required, not optional" in read(path), read(path))

        # --- An optional extension named in `extensions` is not optional.
        #
        # Sphinx raises ExtensionError while importing it and builds no page at all, so
        # writing it into the list flatly contradicts both the comment above it and the
        # message saying the pages will now build. It is imported conditionally instead,
        # with the directive stubbed when it is absent -- otherwise every `.. uml::`
        # becomes an unknown directive and `-W` fails the build for the other reason.
        uml_dir = os.path.join(tmp, "uml")
        outcome, path = sphinx_support.write_conf(
            uml_dir, ("sphinxcontrib.plantuml",), "P")
        body = read(path)
        check("the diagram extension is not in the mandatory list",
              "extensions = []" in body, body)
        check("it is imported conditionally instead",
              "import sphinxcontrib.plantuml" in body and "except ImportError" in body,
              body)
        check("and says that one is optional",
              "every page still builds" in body, body)

        # Both sides, because only one of them is the machine this happens to be.
        with open(os.path.join(uml_dir, "index.rst"), "w", encoding="utf-8") as fh:
            fh.write("Title\n=====\n\n.. uml:: a.puml\n   :caption: c\n")
        with open(os.path.join(uml_dir, "a.puml"), "w", encoding="utf-8") as fh:
            fh.write("@startuml\nclass A\n@enduml\n")

        blocker = os.path.join(tmp, "blocker")
        os.makedirs(blocker)
        with open(os.path.join(blocker, "sitecustomize.py"), "w", encoding="utf-8") as fh:
            fh.write("import sys\n"
                     "class _Block(object):\n"
                     "    def find_module(self, name, path=None):\n"
                     "        if name.startswith('sphinxcontrib.plantuml'): return self\n"
                     "    def load_module(self, name):\n"
                     "        raise ImportError(name)\n"
                     "sys.meta_path.insert(0, _Block())\n")

        if shutil.which("sphinx-build"):
            for label, env in (("installed", None), ("absent", blocker)):
                environ = dict(os.environ)
                if env:
                    environ["PYTHONPATH"] = env
                built = subprocess.run(
                    ["sphinx-build", "-W", uml_dir, os.path.join(uml_dir, "_b_" + label)],
                    capture_output=True, text=True, env=environ)
                check("a page with a diagram builds when the renderer is %s" % label,
                      built.returncode == 0,
                      (built.stdout + built.stderr)[-400:])
                check("and produces HTML either way (%s)" % label,
                      os.path.isfile(os.path.join(uml_dir, "_b_" + label, "index.html")))
        else:
            print("ok   (sphinx-build absent: the two-sided build is not exercised here)")

        outcome, detail = sphinx_support.write_conf(uml_dir, (), "P")
        check("write_conf reports `exists` rather than overwriting", outcome == "exists",
              "%s %s" % (outcome, detail))

        # --- A dangling conf.py symlink is a file that `isfile` says is not there.
        #
        # Writing through it created the target -- outside the output directory, past
        # the promise never to touch an existing configuration and past the script's own
        # "writes only --out". `lexists` sees the link; O_EXCL|O_NOFOLLOW refuses it.
        danger = os.path.join(tmp, "danger")
        os.makedirs(danger)
        victim = os.path.join(tmp, "victim.py")
        os.symlink(victim, os.path.join(danger, "conf.py"))
        outcome, _ = sphinx_support.write_conf(danger, (), "P")
        check("a dangling conf.py symlink is refused", outcome == "exists", outcome)
        check("and nothing is created through it", not os.path.exists(victim))

        with open(victim, "w", encoding="utf-8") as fh:
            fh.write("important = 1\n")
        outcome, _ = sphinx_support.write_conf(danger, (), "P")
        check("a live conf.py symlink is refused too", outcome == "exists", outcome)
        check("and its target is untouched", read(victim) == "important = 1\n")

        # --- The same tree, rendered twice, is the same conf.py.
        first = read(path)
        shutil.rmtree(os.path.join(tmp, "uml"))
        sphinx_support.write_conf(os.path.join(tmp, "uml"),
                                  ("sphinxcontrib.plantuml",), "P")
        check("the same inputs give the same conf.py", read(path) == first)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if FAILURES:
        print("%d failure(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
