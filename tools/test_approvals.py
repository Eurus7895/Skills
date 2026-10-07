#!/usr/bin/env python3
"""Signed approvals: a decision the model cannot write for the user.

Generates throwaway keys with ssh-keygen, so it is skipped -- and says so -- on a machine
without it. CI's runners have it.

    python3 tools/test_approvals.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import approvals  # noqa: E402

SSH = shutil.which("ssh-keygen")
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")


def sh(*args, cwd=None, data=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True,
                          input=data, env=GIT_ENV)


@unittest.skipUnless(SSH, "ssh-keygen is not installed; signed approvals not exercised")
class SignedApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.keys = base / "repo", base / "keys"
        self.build = self.root / ".docs-build"
        self.draft = self.build / "rendered-docs"
        (self.draft / "appendix").mkdir(parents=True)
        self.keys.mkdir()
        for who in ("dana", "mallory"):
            sh(SSH, "-q", "-t", "ed25519", "-N", "", "-C", who, "-f", self.keys / who)
        sh("git", "init", "-q", cwd=self.root)

        (self.build / "template.json").write_text(json.dumps(
            {"template_version": 1, "kind": "preset", "name": "architecture",
             "source": "built-in", "note": "the user picked the architecture report"}))
        (self.build / "checkpoints").mkdir()
        (self.build / "checkpoints" / "P4.json").write_text(json.dumps(
            {"checkpoint": "P4", "state": "decided", "verdict": "accepted",
             "review_queue_hash": "sha256:queue", "input_hash": "sha256:input"}))
        (self.draft / "appendix" / "faq.rst").write_text("FAQ\n===\n\nWritten by Dana.\n")
        (self.build / "doc.json").write_text(json.dumps({"authored_ledger": [
            {"page_id": "appendix/faq", "status": "complete", "owner": "Dana"},
            {"page_id": "appendix/glossary", "status": "waived", "owner": "Dana",
             "waiver_reason": "the product has no domain terms"},
            {"page_id": "appendix/compliance", "status": "waived", "default_waiver": True},
            {"page_id": "changelog", "status": "scaffolded"}]}))

    def signers(self, *who, commit=True):
        lines = []
        for name in who:
            key = (self.keys / (name + ".pub")).read_text().split()
            lines.append('%s@example.com namespaces="docs-approval" %s %s'
                         % (name, key[0], key[1]))
        path = self.root / ".github" / "docs-allowed-signers"
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        if commit:
            sh("git", "add", path, cwd=self.root)
            sh("git", "commit", "-q", "-m", "approvers", cwd=self.root)

    def verify(self):
        return approvals.verify(str(self.build), str(self.draft), str(self.root),
                                approvals.DEFAULT_SIGNERS)

    def sign_all(self, who):
        approvals.write_payloads(str(self.build), str(self.draft))
        for payload in sorted((self.build / "approvals").glob("*.payload")):
            sig = Path(str(payload) + ".sig")
            if sig.exists():
                sig.unlink()
            result = sh(SSH, "-Y", "sign", "-f", self.keys / who, "-n", "docs-approval",
                        payload)
            self.assertEqual(result.returncode, 0, result.stderr)

    def statuses(self, report):
        return {row["name"]: row["status"] for row in report["approvals"]}

    def test_the_right_decisions_need_signing(self):
        names = [name for name, _, _ in approvals.required(str(self.build), str(self.draft))]
        # The default waiver claims nobody, and the scaffolded page settles nothing.
        self.assertEqual(names, ["template", "p4", "authored--appendix__faq",
                                 "authored--appendix__glossary"])

    def test_without_a_signers_file_nothing_is_verified_and_it_says_so(self):
        report, code = self.verify()
        self.assertEqual(code, 0)
        self.assertEqual(report["policy"], "unsigned")
        self.assertIn("not verified", report["reason"])

    def test_an_uncommitted_signers_file_is_not_trusted(self):
        self.signers("dana", commit=False)
        report, code = self.verify()
        self.assertEqual(code, 1)
        self.assertIn("not committed", report["reason"])

    def test_unsigned_approvals_hold_publication(self):
        self.signers("dana")
        report, code = self.verify()
        self.assertEqual(code, 1)
        self.assertEqual(set(self.statuses(report).values()), {"missing"})

    def test_signatures_by_a_listed_key_verify(self):
        self.signers("dana")
        self.sign_all("dana")
        report, code = self.verify()
        self.assertEqual(code, 0, report)
        self.assertEqual(set(self.statuses(report).values()), {"verified"})
        self.assertIn("approvers", report["signers_commit"])

    def test_a_key_not_on_the_list_does_not_count(self):
        self.signers("dana")
        self.sign_all("mallory")
        report, code = self.verify()
        self.assertEqual(code, 1)
        self.assertEqual(set(self.statuses(report).values()), {"unlisted key"})

    def test_an_approval_of_something_since_changed_fails(self):
        self.signers("dana")
        self.sign_all("dana")
        (self.draft / "appendix" / "faq.rst").write_text("FAQ\n===\n\nRewritten later.\n")
        report, code = self.verify()
        self.assertEqual(code, 1)
        self.assertEqual(self.statuses(report)["authored--appendix__faq"], "does not match")
        self.assertEqual(self.statuses(report)["template"], "verified")

    def test_editing_the_signers_file_in_place_is_refused(self):
        self.signers("dana")
        self.sign_all("mallory")
        self.signers("dana", "mallory", commit=False)
        report, code = self.verify()
        self.assertEqual(code, 1)
        self.assertIn("uncommitted changes", report["reason"])

    def test_the_cli_prints_what_the_user_signs(self):
        self.signers("dana")
        result = subprocess.run([sys.executable, script("approvals.py"), "payloads",
                                 "--build", str(self.build), "--draft", str(self.draft),
                                 "--root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("never sign these yourself", result.stdout)
        self.assertIn("ssh-keygen -Y sign -f <their key> -n docs-approval", result.stdout)
        payload = (self.build / "approvals" / "template.payload").read_text()
        self.assertTrue(payload.startswith("docs-approval v1\napproval: template\n"))


if __name__ == "__main__":
    unittest.main()
