#!/usr/bin/env python3
# GENERATED FILE -- DO NOT EDIT.
# Source: shared/scripts/review/validate_draft.py
# Regenerate: python3 tools/materialize.py
"""Refuse final review when rendered output or its source model changed."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from draft_artifact import file_hash, tree_hash  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", required=True)
    parser.add_argument("--doc", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if not os.path.isfile(args.manifest):
        sys.stderr.write("FAIL  no render manifest; run render before review\n")
        return 2
    with open(args.manifest, encoding="utf-8") as fh:
        expected = json.load(fh)
    actual = {"draft_hash": tree_hash(args.draft), "doc_hash": file_hash(args.doc)}
    if any(expected.get(key) != value for key, value in actual.items()):
        sys.stderr.write("FAIL  rendered draft or doc.json changed after render; repair the source and render again\n")
        return 1
    print("rendered draft matches its source model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
