#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/publish/approvals.py
# Regenerate: python3 tools/materialize.py
"""Approvals a person signs, and the check that they did. Stdlib only; runs ssh-keygen.

    python3 approvals.py payloads --build .docs-build --draft .docs-build/rendered-docs
    python3 approvals.py verify --build .docs-build --draft .docs-build/rendered-docs \
        --root . [--signers .github/docs-allowed-signers] [--out approvals-report.json]

Three kinds of decision in this pipeline are the user's: the template choice, the P4
answer to the queued readings, and each authored page settled as complete or waived. The
pipeline records all three as text, and text is something the model driving it can write.

**A repository that commits an allowed-signers file turns them into signatures.** With
`.github/docs-allowed-signers` present -- OpenSSH's allowed_signers format -- every one of
those decisions must carry an SSH signature, made by a key listed there, over a payload
that names exactly what was approved: the template's hash, the review queue's hash, the
page's content hash. `payloads` writes those files and prints the `ssh-keygen -Y sign`
command for each; the user runs them with their own key. `verify` checks every signature
with `ssh-keygen -Y verify` and fails when one is missing, made by an unlisted key, or made
over a payload that no longer matches -- an approval of something that has since changed.

What this proves is that the holder of a listed key signed this exact material. It is as
strong as that key's protection: a passphrase or a hardware key the model cannot use makes
it a real separation, an unprotected key on a machine the model can drive does not. The
signers file is trusted only when it is committed and unmodified, and the report names the
commit that last changed it, because whoever can edit it decides whose signature counts.

Without the file nothing is verified, and the report says so rather than passing silently.

Exit codes: 0 verified (or no signers file, reported as unverified), 1 an approval is
missing or does not verify, 2 bad input or ssh-keygen unavailable, 3 internal error.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

NAMESPACE = "docs-approval"
DEFAULT_SIGNERS = os.path.join(".github", "docs-allowed-signers")
PAYLOAD_VERSION = 1
DRAFT_SUFFIXES = (".rst", ".md")


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def sha256_text(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(subject):
    return json.dumps(subject, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def page_hash(draft, page_id):
    for suffix in DRAFT_SUFFIXES:
        path = os.path.join(draft, page_id + suffix)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                return "sha256:" + hashlib.sha256(fh.read()).hexdigest()
    return None


def required(build, draft):
    """[(name, what, subject)] -- every approval this run needs, and what each covers."""
    out = []
    template = load(os.path.join(build, "template.json"))
    # A provisional template is a recommendation nobody chose; there is nothing to sign
    # until someone does, and `publish` refuses it before signatures are looked at.
    if isinstance(template, dict) and template.get("kind") and not template.get("provisional"):
        out.append(("template", "the template choice", {
            "approval": "template", "kind": template.get("kind"),
            "name": template.get("name"), "template_hash": template.get("template_hash"),
            "selection": template.get("selection"),
            "provisional": bool(template.get("provisional"))}))
    p4 = load(os.path.join(build, "checkpoints", "P4.json"))
    if isinstance(p4, dict) and p4.get("state") == "decided" \
            and p4.get("verdict") == "accepted":
        out.append(("p4", "the P4 answer to the queued readings", {
            "approval": "p4", "verdict": "accepted",
            "review_queue_hash": p4.get("review_queue_hash"),
            "input_hash": p4.get("input_hash")}))
    doc = load(os.path.join(build, "doc.json")) or {}
    for row in doc.get("authored_ledger") or ():
        status = row.get("status")
        if status not in ("complete", "waived"):
            continue
        if status == "waived" and row.get("default_waiver"):
            # Waived by default, in its own words "nobody has looked". There is no person
            # behind it to sign, and it does not claim one.
            continue
        page_id = row.get("page_id", "")
        subject = {"approval": "authored", "page_id": page_id, "status": status,
                   "owner": row.get("owner"), "waiver_reason": row.get("waiver_reason")}
        if status == "complete":
            subject["content_hash"] = page_hash(draft, page_id) if draft else None
        out.append(("authored--" + page_id.replace("/", "__"),
                    "authored page %s (%s)" % (page_id, status), subject))
    return out


def payload(name, what, subject):
    """The exact bytes a person signs: readable, and bound to one subject hash."""
    return ("docs-approval v%d\napproval: %s\nwhat: %s\nsubject: %s\n\n%s\n"
            % (PAYLOAD_VERSION, name, what, sha256_text(canonical(subject)),
               json.dumps(subject, indent=2, sort_keys=True, ensure_ascii=False))
            ).encode("utf-8")


def payload_path(build, name):
    return os.path.join(build, "approvals", name + ".payload")


def write_payloads(build, draft):
    os.makedirs(os.path.join(build, "approvals"), exist_ok=True)
    rows = []
    for name, what, subject in required(build, draft):
        path = payload_path(build, name)
        data = payload(name, what, subject)
        changed = False
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                changed = fh.read() != data
        with open(path, "wb") as fh:
            fh.write(data)
        rows.append((name, what, path, changed and os.path.isfile(path + ".sig")))
    return rows


def git(root, *args):
    try:
        return subprocess.run(["git"] + list(args), cwd=root, capture_output=True,
                              text=True)
    except OSError:
        return None


def signers_trust(root, signers):
    """(trusted, detail): the signers file counts only when it is committed and unedited."""
    relative = os.path.relpath(signers, root)
    tracked = git(root, "ls-files", "--error-unmatch", "--", relative)
    if tracked is None or tracked.returncode != 0:
        return False, ("%s is not committed. A signature checked against a file anyone can "
                       "edit in place proves nothing; commit it first" % relative)
    clean = git(root, "diff", "--quiet", "HEAD", "--", relative)
    if clean is None or clean.returncode != 0:
        return False, ("%s has uncommitted changes. Commit or discard them; the committed "
                       "file is the one that decides whose signature counts" % relative)
    last = git(root, "log", "-1", "--format=%H %an <%ae> %s", "--", relative)
    return True, (last.stdout.strip() if last and last.returncode == 0 else "")


def check_one(ssh, signers, sig, data):
    """(status, principals) for one signature over `data`."""
    if not os.path.isfile(sig):
        return "missing", []
    found = subprocess.run([ssh, "-Y", "find-principals", "-s", sig, "-f", signers],
                           capture_output=True, text=True)
    principals = [p for p in found.stdout.split() if p] if found.returncode == 0 else []
    if not principals:
        return "unlisted key", []
    for principal in principals:
        proc = subprocess.run([ssh, "-Y", "verify", "-f", signers, "-I", principal,
                               "-n", NAMESPACE, "-s", sig], input=data, capture_output=True)
        if proc.returncode == 0:
            return "verified", [principal]
    return "does not match", principals


def verify(build, draft, root, signers_path):
    """The verification report. Never raises for a missing or bad signature."""
    signers = os.path.join(root, signers_path) if not os.path.isabs(signers_path) \
        else signers_path
    needed = required(build, draft)
    report = {"payload_version": PAYLOAD_VERSION, "namespace": NAMESPACE,
              "signers": os.path.relpath(signers, root), "approvals": []}
    if not os.path.isfile(signers):
        report.update(policy="unsigned", verified=False,
                      reason="no %s: approvals are recorded as text and are not verified"
                             % report["signers"])
        report["approvals"] = [{"name": n, "what": w, "status": "unverified"}
                               for n, w, _ in needed]
        return report, 0
    report["policy"] = "signed"
    trusted, detail = signers_trust(root, signers)
    if not trusted:
        report.update(verified=False, reason=detail)
        return report, 1
    report["signers_commit"] = detail
    ssh = shutil.which("ssh-keygen")
    if not ssh:
        report.update(verified=False, reason="ssh-keygen is not installed, so the signatures "
                                             "this repository requires cannot be checked")
        return report, 2
    for name, what, subject in needed:
        status, principals = check_one(ssh, signers, payload_path(build, name) + ".sig",
                                       payload(name, what, subject))
        report["approvals"].append({"name": name, "what": what, "status": status,
                                    "signed_by": principals})
    bad = [a for a in report["approvals"] if a["status"] != "verified"]
    report["verified"] = not bad
    if bad:
        report["reason"] = "%d approval(s) not verified: %s" % (
            len(bad), ", ".join("%s (%s)" % (a["name"], a["status"]) for a in bad))
    return report, 1 if bad else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("payloads", "verify"))
    parser.add_argument("--build", default=".docs-build")
    parser.add_argument("--draft", help="the rendered draft, for authored-page hashes")
    parser.add_argument("--root", default=".", help="the repository being documented")
    parser.add_argument("--signers", default=DEFAULT_SIGNERS,
                        help="allowed-signers file, relative to --root")
    parser.add_argument("--out", help="verify: where to write the report")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.build):
        sys.stderr.write("FAIL no build directory at %s\n" % args.build)
        return 2

    if args.action == "payloads":
        rows = write_payloads(args.build, args.draft)
        signers = os.path.join(args.root, args.signers)
        if not rows:
            print("nothing to approve yet: no template choice, P4 answer or settled "
                  "authored page is recorded")
            return 0
        if not os.path.isfile(signers):
            print("note: no %s, so these approvals will not be verified. Signing them is "
                  "harmless; committing that file is what makes publish require it."
                  % args.signers)
        print("%d approval(s) for the user to sign with their own key -- never sign "
              "these yourself:" % len(rows))
        for name, what, path, stale in rows:
            print("  %-34s %s%s" % (name, what,
                                    "  (CHANGED since it was signed: sign again)"
                                    if stale else ""))
            print("      ssh-keygen -Y sign -f <their key> -n %s %s" % (NAMESPACE, path))
        print("Each command writes <payload>.sig beside its payload; publish verifies them.")
        return 0

    report, code = verify(args.build, args.draft, args.root, args.signers)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")
    if report["policy"] == "unsigned":
        print("approvals UNVERIFIED -- %s" % report["reason"])
        return 0
    for row in report["approvals"]:
        print("%-14s %-34s %s" % (row["status"], row["name"],
                                  ", ".join(row.get("signed_by") or ()) or row["what"]))
    if code:
        print("FAIL %s. Run `pipeline.py approve` for the payloads and have the user sign "
              "them." % report.get("reason"))
    else:
        print("OK %d approval(s) verified against %s (last changed: %s)"
              % (len(report["approvals"]), report["signers"],
                 report.get("signers_commit") or "unknown"))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
